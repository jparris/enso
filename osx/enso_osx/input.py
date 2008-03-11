import logging
import subprocess
import errno
import os
import signal

import objc
import Foundation
import AppKit

# Timer interval in seconds.
_TIMER_INTERVAL = 0.010

# Timer interval in milliseconds.
_TIMER_INTERVAL_IN_MS = int( _TIMER_INTERVAL * 1000 )

KEYCODE_CAPITAL = -1
KEYCODE_SPACE = 49
KEYCODE_LSHIFT = -1
KEYCODE_RSHIFT = -1
KEYCODE_LCONTROL = -1
KEYCODE_RCONTROL = -1
KEYCODE_LWIN = -1
KEYCODE_RWIN = -1
KEYCODE_RETURN = 36
KEYCODE_ESCAPE = 53
KEYCODE_TAB = 48
KEYCODE_BACK = 51
KEYCODE_DOWN = 125
KEYCODE_UP = 126

EVENT_KEY_UP = 0
EVENT_KEY_DOWN = 1
EVENT_KEY_QUASIMODE = 2

KEYCODE_QUASIMODE_START = 0
KEYCODE_QUASIMODE_END = 1
KEYCODE_QUASIMODE_CANCEL = 2

CASE_INSENSITIVE_KEYCODE_MAP = {
    29: "0",
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    23: "5",
    22: "6",
    26: "7",
    28: "8",
    25: "9",
    KEYCODE_SPACE: " ",
    0: "a",
    11: "b",
    8: "c",
    2: "d",
    14: "e",
    3: "f",
    5: "g",
    4: "h",
    34: "i",
    38: "j",
    40: "k",
    37: "l",
    46: "m",
    45: "n",
    31: "o",
    35: "p",
    12: "q",
    15: "r",
    1: "s",
    17: "t",
    32: "u",
    9: "v",
    13: "w",
    7: "x",
    16: "y",
    6: "z",
    44: "?",
    42: "\\",
    47: ".",
    41: ":",
    24: "+",
    27: "-",
    }

class _KeyNotifierController( object ):
    def __init__( self ):
        pass

    def __tryToStartKeyNotifier( self, path="" ):
        fullPath = os.path.join( path, "EnsoKeyNotifier" )
        logging.info( "Trying to launch '%s'." % fullPath )
        popen = subprocess.Popen( [fullPath] )
        return popen

    def start( self ):
        try:
            # First see if the key notifier is on our path...
            popen = self.__tryToStartKeyNotifier()
        except OSError, e:
            if e.errno == errno.ENOENT:
                logging.info( "Couldn't find key notifier on path." )
                # Maybe we're running from a repository checkout...
                import enso_osx
                path = os.path.normpath( enso_osx.__path__[0] + "/../bin" )
                popen = self.__tryToStartKeyNotifier( path )
            else:
                raise

        self._pid = popen.pid

    def stop( self ):
        logging.info( "Stopping key notifier." )
        try:
            os.kill( self._pid, signal.SIGINT )
        except OSError, e:
            if e.errno == errno.ESRCH:
                logging.warn( "Key notifier process no longer exists." )
            else:
                raise

class _Timer( Foundation.NSObject ):
    def initWithCallback_( self, callback ):
        self = super( _Timer, self ).init()
        if self == None:
            return None
        self.__callback = callback
        return self

    def onTimer( self ):
        self.__callback()

class _KeyListener( Foundation.NSObject ):
    def initWithCallback_( self, callback ):
        self = super( _KeyListener, self ).init()
        if self == None:
            return None
        self.__callback = callback
        return self

    def onNotification( self, notification ):
        #print "notification received: %s" % notification.name()
        userInfo = notification.userInfo()
        eventDict = {}
        for key in userInfo:
            eventDict[key] = userInfo.objectForKey_(key)
        self.__callback( eventDict )

    def register( self ):
        self.__center = Foundation.NSDistributedNotificationCenter.defaultCenter()
        self.__center.addObserver_selector_name_object_(
            self,
            self.onNotification,
            u"EnsoKeyNotifier_msg",
            u"EnsoKeyNotifier"
            )

    def unregister( self ):
        self.__center.removeObserver_( self )

class InputManager( object ):
    def __init__( self ):
        self.__shouldStop = False
        self.__mouseEventsEnabled = False
        self.__qmKeycodes = [0, 0, 0]
        self.__isModal = False
        self.__inQuasimode = False

    def __timerCallback( self ):
        self.onTick( _TIMER_INTERVAL_IN_MS )

    def __keyCallback( self, info ):
        if info["event"] == "quasimodeStart":
            self.onKeypress( EVENT_KEY_QUASIMODE,
                             KEYCODE_QUASIMODE_START )
        elif info["event"] == "quasimodeEnd":
            self.onKeypress( EVENT_KEY_QUASIMODE,
                             KEYCODE_QUASIMODE_END )
        elif info["event"] == "someKey":
            self.onSomeKey()
        elif info["event"] in ["keyUp", "keyDown"]:
            keycode = info["keycode"]
            if info["event"] == "keyUp":
                eventType = EVENT_KEY_UP
            else:
                eventType = EVENT_KEY_DOWN
            self.onKeypress( eventType, keycode )
        else:
            logging.warn( "Don't know what to do with event: %s" % info )

    def run( self ):
        logging.info( "Entering InputManager.run()" )

        app = AppKit.NSApplication.sharedApplication()

        timer = _Timer.alloc().initWithCallback_( self.__timerCallback )
        signature = timer.methodSignatureForSelector_( timer.onTimer )
        invocation = Foundation.NSInvocation.invocationWithMethodSignature_(
            signature
            )
        invocation.setSelector_( timer.onTimer )
        invocation.setTarget_( timer )

        Foundation.NSTimer.scheduledTimerWithTimeInterval_invocation_repeats_(
            _TIMER_INTERVAL,
            invocation,
            objc.YES
            )

        keyNotifier = _KeyNotifierController()
        keyNotifier.start()

        keyListener = _KeyListener.alloc().initWithCallback_(
            self.__keyCallback
            )
        keyListener.register()

        try:
            self.onInit()
            while not self.__shouldStop:
                #print "Waiting for event."
                event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    0xffff,
                    Foundation.NSDate.distantFuture(),
                    AppKit.NSDefaultRunLoopMode,
                    objc.YES
                    )
                if event:
                    app.sendEvent_( event )
        finally:
            keyListener.unregister()
            keyNotifier.stop()

        logging.info( "Exiting InputManager.run()" )

    def stop( self ):
        self.__shouldStop = True

    def enableMouseEvents( self, isEnabled ):
        # TODO: Implementation needed.
        self.__mouseEventsEnabled = isEnabled

    def onKeypress( self, eventType, vkCode ):
        pass

    def onSomeKey( self ):
        pass

    def onSomeMouseButton( self ):
        pass

    def onExitRequested( self ):
        pass

    def onMouseMove( self, x, y ):
        pass

    def getQuasimodeKeycode( self, quasimodeKeycode ):
        return self.__qmKeycodes[quasimodeKeycode]

    def setQuasimodeKeycode( self, quasimodeKeycode, keycode ):
        # TODO: Implementation needed.
        self.__qmKeycodes[quasimodeKeycode] = keycode

    def setModality( self, isModal ):
        # TODO: Implementation needed.
        self.__isModal = isModal

    def setCapsLockMode( self, isCapsLockEnabled ):
        # TODO: Implementation needed.
        pass

    def onTick( self, msPassed ):
        pass

    def onInit( self ):
        pass