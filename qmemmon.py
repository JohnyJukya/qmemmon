#!/usr/bin/python
# Qubes Memory Monitor, by Johny Jukya

import argparse
import sys, random
import os
import re
import signal
from PyQt4 import QtCore, QtGui
from PyQt4.QtCore  import *
from PyQt4.QtGui   import *
from time          import sleep
from qubes.qubes   import vmm, QubesVmCollection
from qubes.qmemman import SystemState
from qubes         import qmemman_algo
from math          import cos, sin, sqrt

CACHE_FACTOR=1.1
DOM0_BOOST=350

def M(x):
    return (((int) (x)) + 512) >> 10

def mem():
    qvm_coll = QubesVmCollection()
    qvm_coll.lock_db_for_reading(); qvm_coll.load(); qvm_coll.unlock_db()
    t_used = t_pref = t_aloc = t_swap = t_xtra = 0
    print '%3s %20s %4s %4s %4s %4s %4s  %4s %4s' % \
         ('ID', 'Name', 'Strt', 'Max', 'Swap', 'Used', 'Alloc', 'Pref', 'Xtra')
    print "---------------------------------------------------------------"
    doms = [ ]
    pcts = [ ]
    for vm in [vm for vm in qvm_coll.values()]:
        try:
            dom = {}
            if not vm.is_running(): continue
            aloc = pref = used = vm.memory << 10; swap = 0; meminfo = None
            stat = int(vmm.xs.read('', '/local/domain/%s/memory/static-max' % vm.xid))
            meminfo =  vmm.xs.read('', '/local/domain/%s/memory/meminfo' % vm.xid)
            if meminfo:
                meminfo = qmemman_algo.parse_meminfo(meminfo)
                swap = int(meminfo['SwapTotal']) - int(meminfo['SwapFree'])
                used = int(meminfo['MemTotal' ]) - int(meminfo['MemFree' ]) \
                     - int(meminfo['Cached'   ]) - int(meminfo['Buffers' ]) #+ swap
                aloc = int(vmm.xs.read('', '/local/domain/%s/memory/target' % vm.xid))
                pref = int(used * CACHE_FACTOR)
                if (vm.xid == 0): pref += DOM0_BOOST
            t_used += used; t_aloc += aloc; t_swap += swap; t_pref += pref
            t_xtra += aloc - pref
            print '%3d %20s %4d %4d %4d %4d %4d%s %4d %4d' % (vm.xid, vm.name, vm.memory, 
                M(stat), M(swap), M(used), M(aloc), '*' if meminfo else ' ', 	
                M(pref), M(int(aloc-pref)))
            dom['name'] = vm.name; dom['aloc'] = aloc; dom['used'] = used;
            dom['pref'] = pref;    dom['swap'] = swap; dom['label'] = vm.label.index
            if used != aloc: pcts.append(used * 100.0 / aloc)
            doms.append(dom)
        except Exception:
            pass
    print "--------------------------------------------------------------"
    print '%3s %20s %4s %4s %4d %4d %4d  %4d %4d\n' % ('', 'Totals:', '', '',
            M(t_swap), M(t_used), M(t_aloc), M(t_pref), M(t_xtra))
    if not len(pcts): pcts.append(0)
    return(doms,t_used,t_pref,t_aloc,sum(pcts)/len(pcts))

class Slice(QGraphicsEllipseItem):
    def contextMenuEvent(self, event):
        if self.name == "dom0": return
        menu = QMenu()
        editAction = menu.addAction("Edit " + self.name)
        shutdownAction = menu.addAction("Shutdown " + self.name)
        killAction = menu.addAction("Kill " + self.name)

        action = menu.exec_(event.screenPos())
        if action == editAction:       os.system("qubes-vm-settings " + self.name)
        elif action == shutdownAction: os.system("qvm-shutdown " + self.name)
        elif action == killAction:     os.system("qvm-kill " + self.name)

    def __init__(self, x, y, start, span, color, radius, style, name=None):
        QGraphicsEllipseItem.__init__(self, x, y, radius, radius)
        self.name = name
        self.style = style
        self.setStartAngle(start)
        self.setSpanAngle(span)
        self.setBrush(QBrush(color, style))
        self.setPen(QPen(Qt.white, 1.5))

label_colors = [ 
    0x000000,0xcc0000,0xf57900,0xedd400,0x73d216,0x555753,0x345a4,0x75507b,0x000000,
]

class MemPieView(QGraphicsView):

    def __init__(self):
        self.scene = QGraphicsScene()
        QGraphicsView.__init__(self, self.scene)
        self.setSceneRect(0, 0, 2000, 2000)
        self.setRenderHints(QPainter.Antialiasing|QPainter.TextAntialiasing|
            QPainter.SmoothPixmapTransform|QPainter.HighQualityAntialiasing)
        self.setWindowTitle("Qubes Memory Monitor - by JJ")
        self.scene.setBackgroundBrush(QColor(Qt.darkGray).darker())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumSize(QSize(100, 100))

    def resizeEvent(self, evt):
        self.doupdate()
        self.setSceneRect(0, 0, self.width()-4, self.height()-4)

    def doupdate(self):
        self.populate(*mem())

    def populate(self, doms, t_used, t_pref, t_aloc, pct):
        self.scene.clear()

        fm = QApplication.fontMetrics()
        fh = fm.height()
        start_angle = 0
        max_label_width = max(fm.width(s['name']) for s in doms)

        for dom in doms:
            angle = dom['aloc'] * 16*360 / t_aloc
            clr = QColor(label_colors[dom['label']])

            w = self.width();  self.cx = w / 2
            h = self.height(); self.cy = h / 2
            h -= 8 + 2 * fh
            w -= 8 + 2 * max_label_width
            r = (w if w<h else h)/2 

            s=Slice(self.cx-r, self.cy-r, start_angle, angle, clr, r*2, 
                Qt.SolidPattern, dom['name'])
            s.setToolTip("{}\nAlloc: {} MB\nUsed: {} MB\nCache/Free: {} MB\nSwap: {} MB".format(
                 dom['name'], dom['aloc']>>10, dom['used']>>10, 
                (dom['aloc']-dom['used'])>>10, dom['swap']>>10))
            self.scene.addItem(s)

            # sqrt makes area (vs. radius) proportional to used/alloc mem use

            rb = r*2 * sqrt((float) (dom['pref']) / dom['aloc'])
            s = Slice(self.cx-rb/2,self.cy-rb/2, start_angle, angle, clr, rb, 
                Qt.SolidPattern, dom['name'])
            s.setPen(QPen(Qt.white, 1, Qt.DashLine))
            self.scene.addItem(s)

            rb = r*2 * sqrt((float) (dom['used']) / dom['aloc'])
            s = Slice(self.cx-rb/2,self.cy-rb/2, start_angle, angle, clr, rb, 
                Qt.SolidPattern, dom['name'])
            s.setBrush(QBrush(Qt.white, Qt.Dense6Pattern))
            self.scene.addItem(s)

            rb = r + fm.width("   ")

            abig = (-start_angle - angle/2)
            a = abig * 3.14159 * 2 / 360 / 16
            l = QGraphicsSimpleTextItem(dom['name'])
            x = self.cx+int(cos(a) * rb); y = self.cy+int(sin(a) * rb)
            w = fm.width(dom['name'])
            l.setPos(x-(w if x<self.cx else 0), y-fm.height()/2)
            l.setBrush(QBrush(Qt.white))
            self.scene.addItem(l)

            qf = QFont("Helvetica", 12)
            status = "Avg:{:5.1f}%".format(pct)
            self.status_offset = QFontMetrics(qf).width("Avg: ")
            t = QGraphicsSimpleTextItem(status)
            t.setPos(0, 0)
            t.setFont(qf)
            t.setBrush(QBrush(Qt.green))
            self.setWindowTitle(status + " - Qubes Memory Monitor by JJ")
            self.scene.addItem(t)

            start_angle += angle

    def sizeHint(self):
        return QSize(420, 300)

    def sizePolicy(self):
        return QSizePolicy.Expanding

DEFAULT_INTERVAL=2

def main(args):

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    parser=argparse.ArgumentParser()
    parser.add_argument("-i", "--interval", help="update interval in seconds, default {}".format(DEFAULT_INTERVAL), type=int)
    parser.add_argument("-n", "--notontop", help="don't keep window on top", nargs='?', default=0, const=1)
    args = parser.parse_args()

    with open("/etc/qubes/qmemman.conf") as f:  # Qubes lib was awkward to use
        for line in f:
            m = re.search('^cache-margin-factor *= *([0-9.]*)$', line)
            if m: CACHE_FACTOR = float(m.group(1))
            m = re.search('^dom0-mem-boost *= *([0-9]*)', line)
            if m: DOM0_BOOST= int(m.group(1))

    app = QApplication(sys.argv)
    mem_view = MemPieView()
    if not args.notontop:
        mem_view.setWindowFlags(mem_view.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

    app_icon = QtGui.QIcon()
    app_icon.addFile('qmemmon48x48.png', QtCore.QSize(48,48))
    app.setWindowIcon(app_icon)

    tray = QSystemTrayIcon()
    tray.setIcon(app_icon)
    tray.setToolTip("Qubes Memory Monitor")
    tray.show()

    mem_view.show()

    fm = QApplication.fontMetrics()

    def refresh():
        mem_view.doupdate()
        img = QPixmap.grabWidget(mem_view, mem_view.status_offset, 0, 24, 24)
        tray.setIcon(QIcon(img))

    timer = QTimer();
    timer.timeout.connect(refresh)
    timer.start(1000 * (args.interval if args.interval else DEFAULT_INTERVAL))

    tray.showMessage("Started", "Monitor started")
    refresh()
    app.exec_()

if __name__ == "__main__":
    main(sys.argv)
