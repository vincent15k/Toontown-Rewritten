from direct.distributed.DistributedObjectGlobalUD import DistributedObjectGlobalUD
from direct.distributed.PyDatagram import *
from direct.directnotify.DirectNotifyGlobal import directNotify
from PartyGlobals import *
from datetime import datetime, timedelta

class GlobalPartyManagerUD(DistributedObjectGlobalUD):
    notify = directNotify.newCategory('GlobalPartyManagerUD')

    # This uberdog MUST be up before the AIs, as AIs talk to this UD
    
    def announceGenerate(self):
        DistributedObjectGlobalUD.announceGenerate(self)
        self.notify.debug("GPMUD generated")
        self.senders2Mgrs = {}
        self.host2PartyId = {} # just a reference mapping
        self.id2Party = {} # This should be replaced with a longterm datastore
        self.party2PubInfo = {} # This should not be longterm
        PARTY_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
        startTime = datetime.strptime('2014-01-20 11:50:00', PARTY_TIME_FORMAT)
        endTime = datetime.strptime('2014-01-20 12:20:00', PARTY_TIME_FORMAT)
        #self.host2Party[100000001] = {'hostId': 100000001, 'start': startTime, 'end': endTime, 'partyId': 1717986918400000, 'decorations': [[3,5,7,6]], 'activities': [[10,13,6,18],[7,8,7,0]],'inviteTheme':1,'isPrivate':0,'inviteeIds':[]}

        # Setup tasks
        self.runAtNextInterval()

    # GPMUD -> PartyManagerAI messaging
    def _makeAIMsg(self, field, values, recipient):
        return self.air.dclassesByName['DistributedPartyManagerUD'].getFieldByName(field).aiFormatUpdate(recipient, recipient, simbase.air.ourChannel, values)

    def sendToAI(self, field, values, sender=None):
        if not sender:
            sender = self.air.getAvatarIdFromSender()
        dg = self._makeAIMsg(field, values, self.senders2Mgrs[sender])
        self.air.send(dg)
        
    # GPMUD -> toon messaging
    def _makeAvMsg(self, field, values, recipient):
        return self.air.dclassesByName['DistributedToonUD'].getFieldByName(field).aiFormatUpdate(recipient, recipient, simbase.air.ourChannel, values)

    def sendToAv(self, avId, field, values):
        dg = self._makeAvMsg(field, values, avId)
        self.air.send(dg)
        
    # Task stuff
    def runAtNextInterval(self):
        now = datetime.now()
        howLongUntilAFive = (60 - now.second) + 60 * (4 - (now.minute % 5))
        taskMgr.doMethodLater(howLongUntilAFive, self.__checkPartyStarts, 'GlobalPartyManager_checkStarts')

    def canPartyStart(self, party):
        now = datetime.now()
        delta = timedelta(minutes=15)
        endStartable = party['start'] + delta
        return True#party['start'] < now and endStartable > now

    def isTooLate(self, party):
        now = datetime.now()
        delta = timedelta(minutes=15)
        endStartable = party['start'] + delta
        return endStartable > now

    def __checkPartyStarts(self, task):
        now = datetime.now()
        for partyId in self.id2Party:
            party = self.id2Party[partyId]
            if self.canPartyStart(party):
                # Time to start party
                hostId = party['hostId']
                party['status'] = PartyStatus.CanStart
                self.sendToAv(hostId, 'setHostedParties', [[self._formatParty(party)]])
                self.sendToAv(hostId, 'setPartyCanStart', [partyId])
            elif self.isTooLate(party):
                party['status'] = PartyStatus.NeverStarted
                self.sendToAv(hostId, 'setHostedParties', [[self._formatParty(party)]])
        self.runAtNextInterval()

    # Format a party dict into a party struct suitable for the wire
    def _formatParty(self, partyDict):
        start = partyDict['start']
        end = partyDict['end']
        return [partyDict['partyId'],
                partyDict['hostId'],
                start.year,
                start.month,
                start.day,
                start.hour,
                start.minute,
                end.year,
                end.month,
                end.day,
                end.hour,
                end.minute,
                partyDict['isPrivate'],
                partyDict['inviteTheme'],
                partyDict['activities'],
                partyDict['decorations'],
                partyDict.get('status', PartyStatus.Pending)]

    # Avatar joined the game, invoked by the CSMUD
    def avatarJoined(self, avId):
        partyId = self.host2PartyId.get(avId, None)
        if partyId:
            party = self.id2Party[partyId]
            self.sendToAv(avId, 'setHostedParties', [[self._formatParty(party)]])
            if partyId not in self.party2PubInfo and self.canPartyStart(party):
                # The party hasn't started and it can start
                self.sendToAv(avId, 'setPartyCanStart', [partyId])

    # uberdog coordination of public party info
    def __updatePartyInfo(self, partyId):
        # Update all the AIs about this public party
        party = self.party2PubInfo[partyId]
        for sender in self.senders2Mgrs:
            actIds = []
            for activity in self.id2Party[partyId]['activities']:
                actIds.append(activity[0]) # First part of activity tuple should be actId
            self.sendToAI('updateToPublicPartyInfoUdToAllAi', [party['shardId'], party['zoneId'], partyId, self.id2Party[partyId]['hostId'], party['numGuests'], party['maxGuests'], party['hostName'], actIds])

    def __updatePartyCount(self, partyId):
        # Update the party guest count
        for sender in self.senders2Mgrs:
            pass

    def partyHasStarted(self, partyId, shardId, zoneId, hostName):
        self.party2PubInfo[partyId] = {'partyId': partyId, 'shardId': shardId, 'zoneId': zoneId, 'hostName': hostName, 'numGuests': 0, 'maxGuests': MaxToonsAtAParty}
        self.__updatePartyInfo(partyId)
        # update the host's book
        party = self.id2Party.get(partyId, None)
        self.id2Party[partyId]['status'] = PartyStatus.Started
        if not party:
            self.notify.warning("didn't find details for starting party id %s hosted by %s" % (partyId, hostName))
            return
        self.sendToAv(party['hostId'], 'setHostedParties', [[self._formatParty(party)]])

    def toonJoinedParty(self, partyId, avId):
        pass
    def toonLeftParty(self, partyId, avId):
        pass

    def partyManagerAIHello(self, channel):
        # Upon AI boot, DistributedPartyManagerAIs are supposed to say hello. 
        # They send along the DPMAI's doId as well, so that I can talk to them later.
        print 'AI with base channel %s, will send replies to DPM %s' % (simbase.air.getAvatarIdFromSender(), channel)
        self.senders2Mgrs[simbase.air.getAvatarIdFromSender()] = channel
        self.sendToAI('partyManagerUdStartingUp', [])
        
        # In addition, set up a postRemove where we inform this AI that the UD has died
        self.air.addPostRemove(self._makeAIMsg('partyManagerUdLost', [], channel))
        
    def addParty(self, avId, partyId, start, end, isPrivate, inviteTheme, activities, decorations, inviteeIds):
        PARTY_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
        print 'start time: %s' % start
        startTime = datetime.strptime(start, PARTY_TIME_FORMAT)
        endTime = datetime.strptime(end, PARTY_TIME_FORMAT)
        print 'start year: %s' % startTime.year
        if avId in self.host2PartyId:
            # Sorry, one party at a time
            self.sendToAI('addPartyResponseUdToAi', [partyId, AddPartyErrorCode.TooManyHostedParties])
        self.id2Party[partyId] = {'partyId': partyId, 'hostId': avId, 'start': startTime, 'end': endTime, 'isPrivate': isPrivate, 'inviteTheme': inviteTheme, 'activities': activities, 'decorations': decorations, 'inviteeIds': inviteeIds, 'status': PartyStatus.Pending}
        self.host2PartyId[avId] = partyId
        self.sendToAI('addPartyResponseUdToAi', [partyId, AddPartyErrorCode.AllOk, self._formatParty(self.id2Party[partyId])])
        taskMgr.remove('GlobalPartyManager_checkStarts')
        taskMgr.doMethodLater(15, self.__checkPartyStarts, 'GlobalPartyManager_checkStarts')
        return
        
    def queryParty(self, hostId):
        # An AI is wondering if the host has a party. We'll tell em!
        if hostId in self.host2PartyId:
            # Yep, he has a party.
            party = self.id2Party[self.host2PartyId[hostId]]
            self.sendToAI('partyInfoOfHostResponseUdToAi', [self._formatParty(party), party.get('inviteeIds', [])])
            return
        print 'query failed, av %s isnt hosting anything' % hostId
        
    def requestPartySlot(self, partyId, avId, gateId):
        if partyId not in self.party2PubInfo:
            return # TODO there's a client error code I can send
        party = self.party2PubInfo[partyId]
        if party['numGuests'] >= party['maxGuests']:
            return # TODOOOOO send the right error code saying it's now full
        # get them a slot
        party['numGuests'] = party['numGuests'] + 1
        
        # now format the pubPartyInfo
        actIds = []
        for activity in self.id2Party[partyId]['activities']:
            actIds.append(activity[0])
        info = [party['shardId'], party['zoneId'], party['numGuests'], party['hostName'], actIds, 0] # the param is minleft
        # find the hostId
        hostId = self.id2Party[party['partyId']]['hostId']
        # send update to client's gate
        recipient = avId + (1001L << 32)
        sender = simbase.air.getAvatarIdFromSender() # try to pretend the AI sent it. ily2 cfsworks
        dg = self.air.dclassesByName['DistributedPartyGateAI'].getFieldByName('setParty').aiFormatUpdate(gateId, recipient, sender, [info, hostId])
        self.air.send(dg)
