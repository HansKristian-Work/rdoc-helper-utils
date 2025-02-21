from typing import Optional
import qrenderdoc as qrd
import renderdoc as rd

class Window(qrd.CaptureViewer):
    def __init__(self, ctx : qrd.CaptureContext):
        super().__init__()
        self.mqt : qrd.MiniQtHelper = ctx.Extensions().GetMiniQtHelper()
        self.ctx = ctx
        self.topWindow = self.mqt.CreateToplevelWidget("Masher", lambda c, w, d: window_closed())
        self.button = self.mqt.CreateButton(lambda ctx, widget, text: self.press())
        self.mqt.AddWidget(self.topWindow, self.button)
        self.mqt.SetWidgetText(self.button, 'MASH EID >:D')

    def press(self):
        eid = self.ctx.CurEvent()
        print('Mashing EID', eid)
        if eid != 0:
            self.ctx.SetEventID([], eid, eid, True)

cur_window : Optional[Window] = None

def window_closed():
    global cur_window
    if cur_window is not None:
        cur_window.ctx.RemoveCaptureViewer(cur_window)
    cur_window = None

def mash_callback(ctx : qrd.CaptureContext, data):
    global cur_window
    print('Trying to open window ...')
    mqt = ctx.Extensions().GetMiniQtHelper()
    if cur_window is None:
        cur_window = Window(ctx)
        if ctx.HasEventBrowser():
            ctx.AddDockWindow(cur_window.topWindow, qrd.DockReference.TopOf, ctx.GetEventBrowser().Widget(), 0.1)
        else:
            ctx.AddDockWindow(cur_window.topWindow, qrd.DockReference.MainToolArea, None)

    ctx.RaiseDockWindow(cur_window.topWindow)


def register(version : str, ctx : qrd.CaptureContext):
    print('Loading masher for version {}'.format(version))
    ctx.Extensions().RegisterWindowMenu(qrd.WindowMenu.Window, ["Open Mash EDID button"], mash_callback)

def unregister():
    print('Unregistering masher')
    global cur_window
    if cur_window is not None:
        cur_window.ctx.Extensions().GetMiniQtHelper().CloseToplevelWidget(cur_window.topWindow)
        cur_window = None
