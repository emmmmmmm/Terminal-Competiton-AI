from em_player import Player
from em_timer import Timer
from em_gameGrid import GameGrid
from em_score import Score
from em_util import BuildQueue
import em_util
import em_log as debug
from em_strategy import Strategy
import gamelib
from gamelib import debug_write
import random
import copy
import em_buildingPlans as BuildingPlans
import em_pathing as Pathing
# import em_pathing
#------------------------------------------------------------------
# THE BRAIN CLASS!!
#------------------------------------------------------------------


class Brain:
    def __init__(self):
        debug.ACTIVE = False
        self.timer = Timer()
        self.log = []

        self.history = []
        self.hits = [] #set from on_action
        self.damage = [] #set from on_action
        self.game_state = []  #set from update
        self.enemyUnits = [] # set from on_action
        self.playerUnits = [] #set from on_action

        self.playerScores = []
        self.enemyScores = []
        self.enemyHealth = 30
        self.playerHealth= 30

        # is anything here still in use?? - don't think so.
        self.enemySpawnPoints = []
        self.enemyHitPoints = []
        self.enemyPaths = []
        self.playerPaths = []
        self.spawn = []

        self.enemyEdgePoints = [] # set on setup
        self.playerEdgePoints = []# set on setup

        self.enemyScored = False
        self.playerScored = False



    #------------------------------------------------------------------
    def start(self,game_state):
        self.game_state = game_state
        self.playerEdgePoints = em_util.getEdgePoints(game_state,0)
        self.enemyEdgePoints = em_util.getEdgePoints(game_state,1)
        self.allLocations = em_util.getAllLocations(game_state)

        self.gameGrid = GameGrid(game_state.game_map)

        self.player = Player(playerIndex=0, game_state = game_state)
        self.enemy  = Player(playerIndex=1, game_state = game_state)

        self.strategy = Strategy(game_state,self.player,self.enemy,self)
        self.buildQueue = BuildQueue()
        debug.print("-------------------------------")
        debug.print(" init done - ready for action! ")
        debug.print("-------------------------------")
    #------------------------------------------------------------------
    def update(self,game_state):
        debug.print("")
        debug.print(" ===== turn {}  ===== ".format(game_state.turn_number))
        debug.print("")
        game_state.suppress_warnings(True) # do I need to re-set this every turn?

        self.timer.reset()
        self.game_state = game_state

        # analyze what happend last turn:
        self.analyzeActionPhase()

        if self.GridChanged(): # this could speed things up by quite a bit!
            self.playerScores = Pathing.GetScores(self.player, self.gameGrid,self.game_state, optimized = True)
            self.enemyScores  = Pathing.GetScores(self.enemy, self.gameGrid,self.game_state, optimized = False)

        debug.print("Getting all scores took {:.2f} seconds".format(self.timer.timePassed()))

        # print map to console
        #debug.print_scores(self.playerScores)

        # update players
        self.player.Update(self.playerUnits[-1] if self.playerUnits else [],
                           self.game_state,
                           self.playerScores)
        self.enemy.Update(self.enemyUnits[-1] if self.enemyUnits else [],
                          self.game_state,
                         self.enemyScores)

        # all info is gathered, build strategy!
        self.createStrategy()

        # i can use timer.timeLeft() to check if I have time to do some more work...!
        if self.timer.timeLeft()>2: # seconds
            pass
             # TODO: can i prepare something for next turn?

        debug.print("--------------------")
        debug.print("player: {} / enemy: {}".format(self.player.health[-1],self.enemy.health[-1]))
        debug.print("processing turn {} took {:.2f} secs".format(game_state.turn_number,self.timer.timePassed()))

    #------------------------------------------------------------------
    def createStrategy(self):
        #funcs
        spawnUnits = self.game_state.attempt_spawn
        deleteUnits = self.game_state.attempt_remove
        # update strategy base values
        self.strategy.reset(self.game_state,self.player,self.enemy)
        # look at bestScore, and the best health score, and see if there's a point in sending pings!
        healthScores = self.GetScoresByHealth(self.player.index)

        # don't spawn too many encryptors...
        # TODO: move this someplace else? ... Strategy comes to mind for example
        self.strategy.spawnEncryptors = True
        encs = len(self.gameGrid.getUnitsOfType(self.game_state.ENCRYPTOR,self.player.index))
        #self.print("Player has {} encryptors on the field".format(encs))
        if encs > 5:
            self.strategy.spawnEncryptors = False

        # create strategy for this turn:
        currentStrategy = "adaptive"
        side = None
        playerThreatLevel = self.player.ThreatLevel(attackCost = 10) # default attack
        enemyThreatLevel = self.enemy.ThreatLevel()

        # debug print for balancing:
        debug.print("PLAYER: Cores: {} Bits: {}".format(self.player.cores, self.player.bits))
        debug.print("ENEMY : Cores: {} Bits: {}".format(self.enemy.cores, self.enemy.bits))
        debug.print("SCORE: {:.2f} / HEALTH: {}".format(self.player.bestScore.value, healthScores[0].health))
        #debug.print("Value Near Spawn: {}".format(self.player.bestScore.valueNearSpawn))
        debug.print("THREAT: player: {:.2f} (score: {:.2f})".format(playerThreatLevel,self.player.bestScore.value))
        debug.print("THREAT: enemy:  {:.2f} (score: {:.2f})".format(enemyThreatLevel,self.enemy.bestScore.value))




        # first turns
        if self.game_state.turn_number<2:
            #side = "left"
            currentStrategy = "maze"
            self.strategy.AddUnits(self.game_state.PING,10,self.player.bestScore.startPoint)

        # if self destructing
        elif not self.player.bestScore.pathToEnd:
            # check if i should build a cannon
            # i'm kinda safe here, so dont worry if it takes a couple of turns
            side = self.player.CanSpawnCannon(self.gameGrid,self.enemy) # "left"/"right"/False
            if side:
                currentStrategy = "pingCannon"
                self.strategy.AddUnits(self.game_state.PING,19,BuildingPlans.GetPingCannonSpawn(side)) # spwn will be overwritten
            else:
                currentStrategy = "adaptive" # no need to re-set this
                self.strategy.AddUnits(self.game_state.PING,19,self.player.bestScore.startPoint)

        # VALUE: adjust maximum thresholds
        elif playerThreatLevel < 1 or healthScores[0].health < 200: # VALUE # should score w/ default attack:
            self.strategy.AddUnits(self.game_state.PING,10,self.player.bestScore.startPoint)
        else: # playerThreatLevel >= 1

            if self.player.ThreatLevel(attackCost = 19) < 1: # bigger attack might score
                self.strategy.AddUnits(self.game_state.PING,19,self.player.bestScore.startPoint)
            else:
                side = self.player.CanSpawnCannon(self.gameGrid,self.enemy)
                if side:
                    currentStrategy = "pingCannon"
                    self.strategy.AddUnits(self.game_state.PING,19,BuildingPlans.GetPingCannonSpawn(side))
                else:
                    # well fuck^^
                    # impenetrable defense and not able to build a cannon... what to do now?
                    currentStrategy = "maze"
                    self.strategy.AddUnits(self.game_state.EMP,5,BuildingPlans.GetMazeSpawn())


        self.strategy.SetCurrentStrategy(currentStrategy, side, enemyThreatLevel)

        # sheduled reconstruction:
        # TODO: think about this?
        self.buildQueue.process(self.game_state,self.strategy.notBuildAllowed)



        self.strategy.CreateOffense()
        self.strategy.CreateDefense()

        self.strategy.DeployDefense()
        self.strategy.DeployOffense()



        # TODO: OOOhhh I could use the unusedUnits to figure out if i can replace some destructors with filters!
        # still won't work, bc/ then i'd delete part of my maze on future turns... -,-
        #if self.game_state.turn_number > 10 and currentStrategy == "maze":
        #    self.RemoveUnusedUnits()


        # add critical units to queue to be replaced!
        # TODO: think about when this is a good strategy..!
        # maybe only do this for units that are in/near my enemys best path?
        locsToRebuild, unitsToRebuild = self.GetCriticalUnits(encryptors=False)


        if unitsToRebuild:
            deleteUnits(locsToRebuild)
            self.buildQueue.push(unitsToRebuild)

    #------------------------------------------------------------------
    def GetCriticalUnits(self,playerIndex = 0, encryptors = True):
        unitsToRebuild = self.gameGrid.getCriticalUnits(playerIndex)
        if not encryptors:
            unitsToRebuild = [unit for unit in unitsToRebuild if unit.type is not self.game_state.ENCRYPTOR]

        locs = [unit.pos for unit in unitsToRebuild]
        type = [[unit.type, unit.pos] for unit in unitsToRebuild]

        return locs, type
    #------------------------------------------------------------------
    def RemoveUnusedUnits(self):
        # Remove unused units -> figure out WHEN this is apropriate...!
        unused = self.gameGrid.getUnusedUnits(self.player.index)
        locs = [p.pos for p in unused if p.type != self.game_state.ENCRYPTOR]
        if locs:
            deleteUnits(locs)

    #------------------------------------------------------------------
    def analyzeActionPhase(self):
        # update history
        currentPlayer0InfoUnits = []
        currentPlayer1InfoUnits = []
        game_state = self.game_state
        map = game_state.game_map
        allLocations = map.get_all_locations
        allUnits = map.get_all_units

        currentUnits = allUnits()

        currentPlayer0InfoUnits = [unit for unit in currentUnits if not(unit.stationary ) and unit.player_index == 0]
        currentPlayer1InfoUnits = [unit for unit in currentUnits if not(unit.stationary ) and unit.player_index == 1]


        self.history.append(currentUnits) # could be used to predict if a unit well be rebuilt (and their order of rebuilding etc...)!



        # update the map:
        # replace destroyed enemy units
        self.game_state = em_util.replaceDeletedEnemyUnits(game_state,self.history)

        # do not consider enemy units that are marked for deletion

        """
        for location in allLocations():
            if not map[location]:
                continue
            if map[location][0].pending_removal:
                map.remove_unit(location)
        """
        # this should work, no?
        for unit in currentUnits:
            if unit.pending_removal:
                self.print("removing unit {} bc marked for deletion".format(unit.pos))
                map.remove_unit(unit.pos)


        # process previous ActionState:
        # check if someone scored -> to be used laters
        self.enemyScored = False
        self.playerScored = False

        if game_state.my_health <self.playerHealth:
            self.enemyScored = True
            self.print("SCORE: enemy scored ({})".format(self.playerHealth-game_state.my_health))
        if game_state.enemy_health < self.enemyHealth:
            self.playerScored = True
            self.print("SCORE: player scored ({})".format(self.enemyHealth-game_state.enemy_health))
        self.enemyHealth = game_state.enemy_health
        self.playerHealth = game_state.my_health

        # update gameGrid
        self.gameGrid.update(game_state.game_map)
        return
    #------------------------------------------------------------------
    def GridChanged(self):
        if(len(self.history)>1):
            changed = [x for x in self.history[-1] if x not in self.history[-2]] # those are only units added, not units removed...
            changed += [x for x in self.history[-2] if x not in self.history[-1]]
            return len(changed)>0
            #return set(tuple(self.history[-1])) == set(tuple(self.history[-2])) # slow??
        return True #
    #------------------------------------------------------------------
    def dumpLog(self):
        debug.dumpLog()
    #------------------------------------------------------------------
    def GetScoresByHealth(self, playerIndex):
        healthScores = self.player.scores[:] # copy, just to make sure
        healthScores.sort(key = lambda x: x.health, reverse = False) # sort by Score -> lowest first
        return healthScores
    #------------------------------------------------------------------
    def print(self,msg):
        debug.print(msg)
