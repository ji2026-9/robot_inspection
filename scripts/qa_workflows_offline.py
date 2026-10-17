import os,sys,time,uuid,traceback
from pathlib import Path
from unittest.mock import patch,MagicMock
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root/'software'),str(root/'tests')]
os.environ['QT_QPA_PLATFORM']='windows'
from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat,QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
fmt=QSurfaceFormat();fmt.setVersion(2,1);fmt.setProfile(QSurfaceFormat.CompatibilityProfile);fmt.setDepthBufferSize(24);QSurfaceFormat.setDefaultFormat(fmt)
app=QApplication([]);app.setStyle('Fusion');QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');app.setFont(QFont('Microsoft YaHei',10))
import copy,json,numpy as np
from inspection_gui.probe_stop import ProbeStopMonitor
fixture_frame=json.loads((root/'tests/fixtures/offline_feedback.json').read_text())
def sample():return dict(copy.deepcopy(fixture_frame),received_monotonic=time.monotonic(),pose_stable=True)
class Backend:
    address='127.0.0.1';generation=1;identity=None;manual_control=None
    def __init__(self):self.stop_monitor=ProbeStopMonitor()
    def snapshot(self):return sample()
    def is_connected(self):return True
    def probe_events_since(self,sequence):return dict(events=[],latest_sequence=0,missed_events=0)
from inspection_gui.gui import MainWindow
from inspection_gui.probe_workspace_view import ProbeWorkspaceDialog
from inspection_gui.devices_view import _registered_backends
from experiment_records import ExperimentRecords
out=root/'.test-output'/'workflow-qa';fixture=out/'integrated_qa'/uuid.uuid4().hex;fixture.mkdir(parents=True)
backend=Backend();backend.snapshot=sample;backend.disconnect=MagicMock();camera=MagicMock();camera.is_connected.return_value=False
errors=[];sys.excepthook=lambda *exc:(errors.append(''.join(traceback.format_exception(*exc))),sys.__excepthook__(*exc))
def pump(seconds=.1):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.003)
def workspace(self):
    if not hasattr(self,'_probe_workspace_dialog'):
        self._probe_workspace_dialog=ProbeWorkspaceDialog(self,storage_path=fixture/'positions.json',embedded=True)
        self._probe_workspace_dialog.workbench_router=self.workbench.open_page
    return self._probe_workspace_dialog
from inspection_gui import global_wall as gw
from inspection_gui.safety_wall import load_wall
from inspection_gui.safety_wall_view import SafetyWallDialog
checks=[]
with patch('socket.create_connection',side_effect=AssertionError('No hardware networking')),patch.dict(_registered_backends,{'robot_b':backend,'robot_a':camera,'camera':camera}),patch.object(MainWindow,'auto_connect_camera',lambda self:None),patch.object(MainWindow,'_probe_page',workspace),patch.object(gw,'DEFAULT_PATH',fixture/'safety_wall.json'),patch('inspection_gui.simulation_view.compile_trajectory',return_value=([],[])):
    main=MainWindow(ExperimentRecords(fixture/'records.json'));main.resize(1440,940)
    main.setWindowTitle('多目标控制离线验收 · 不连接实机');main.show();pump();main.grab().save(str(out/'精简流程首页.png'))
    assert main.utility_group.isHidden() and main.photo_group.isHidden()
    assert main.result_empty.isVisible() and main.table.isHidden()
    assert len(main.visual_tools.menu().actions())==4
    main.current_result={'detected_holes':[]};main.refresh_current_summary();assert not main.table.isHidden() and main.result_empty.isHidden()
    main.current_result=None;main.refresh_current_summary();assert main.table.isHidden() and not main.result_empty.isHidden()
    p=main.workbench.open_page('control');p.open_coordinate_target();pump(.4)
    assert main.global_status.stop.isHidden() and not p.stop_button.isHidden()
    assert p.reset_button.isHidden() and p.end_button.isHidden()
    assert '位置未确认' in main.wall_summary.text()
    assert not (fixture/'safety_wall.json').exists()
    assert p.controller.wall_guard is not None
    checks.append('unknown geometry displayed globally; actual motion locked; no default file written')
    p.xyz[0].setValue(-650.);p.generate_target_preview()
    deadline=time.monotonic()+10
    while p.preview_view.busy and time.monotonic()<deadline:pump(.03)
    pump();assert p.preview_view.plan,p.preview_view.note.text()
    p.add_waypoint();p.xyz[1].setValue(p.xyz[1].value()+20);p.add_waypoint();p.xyz[0].setValue(-630);p.add_waypoint();p.route_list.item(1).setCheckState(Qt.Unchecked);p.generate_target_preview()
    deadline=time.monotonic()+20
    while p.preview_view.busy and time.monotonic()<deadline:pump(.03)
    pump();assert p.preview_view.plan,p.preview_view.note.text()
    assert len(p.preview_view.plan['targets'])==2
    assert p.preview_view.scene.isValid() and not p.preview_view.scene.render_error
    assert 1.19<=p.preview_view.scene.width()/p.preview_view.scene.height()<=2.21
    assert p.preview_view.scene.height()>300,(p.preview_view.scene.width(),p.preview_view.scene.height())
    p.control_scroll.ensureWidgetVisible(p.route_list);pump(.2);main.grab().save(str(out/'精简流程_目标表.png'))
    assert len(p.preview_view.plan['targets'])==2
    assert p.preview_view.plan['targets'][1][:3]==p.waypoints[2]
    p.set_origin_input();assert p.origin_path.exists();assert not p.controller.connected
    p.preview_origin()
    deadline=time.monotonic()+15
    while p.preview_view.busy and time.monotonic()<deadline:pump(.03)
    pump();assert p.preview_view.plan,p.preview_view.note.text()
    assert p.preview_view.plan['target'][:3]==p.origin['xyz']
    p.control_scroll.ensureWidgetVisible(p.return_origin_button);pump(.2)
    main.grab().save(str(out/'自定义原点_回原点预览.png'))
    before=p.preview_view.scene.size();p.preview_view.expand_button.setChecked(True);pump(.3)
    assert p.preview_view.scene.width()>before.width() and p.stop_button.isVisible()
    main.grab().save(str(out/'实机控制_新版放大预览.png'))
    p.preview_view.expand_button.setChecked(False);pump(.2)
    p.clear_waypoints();p.copy_position();p.add_waypoint();p.generate_target_preview()
    deadline=time.monotonic()+10
    while p.preview_view.busy and time.monotonic()<deadline:pump(.03)
    pump();assert p.detail.isVisible() and p.detail.level=='error',p.detail.text()
    assert '第 1 个执行目标' in p.detail.text() and '下一步' in p.detail.text()
    assert p.stop_button.mapTo(main,p.stop_button.rect().bottomRight()).y()<main.height(), 'Stop clipped by feedback banner'
    main.grab().save(str(out/'精简流程_错误反馈.png'))
    probe=main.workbench.open_page('probe');probe.message('保存失败：离线示例目录无写入权限',True);pump(.2)
    main.grab().save(str(out/'操作提示_测头任务.png'))
    wall=main.workbench.open_page('wall');pump(.2)
    wall.editor.fields['margin_mm'].setValue(400);wall.editor.save();pump(.2)
    assert wall.editor.result.level=='error'
    main.grab().save(str(out/'操作提示_安全墙报错.png'))
    main.workbench.open_page('control');pump(.2)
    main.global_wall.warn('离线模拟：目标路径进入墙面停止预留区','虚拟预览');pump(.3)
    assert main.wall_alerts.box and main.wall_alerts.box.isVisible()
    main.wall_alerts.box.grab().save(str(out/'安全墙_弹窗预警.png'))
    main.wall_alerts.box.accept();pump()
    assert not p.controller.connected
    checks.append('visible persistent errors and next actions, invalid selected target with coordinates, wall validation notice, probe notice, checkbox selection, persisted custom origin, separate return preview, two target route, real OpenGL rendering, expanded preview, visible Stop and nonblocking warning; no hardware networking')
    main.workbench.open_page('control');pump(.1)
    p.clear_waypoints();p.copy_position();p.add_waypoint()
    p.preview_origin()
    deadline=time.monotonic()+10
    while p.preview_view.busy and time.monotonic()<deadline:pump(.03)
    assert p.preview_view.plan and p.preview_view.plan['purpose']=='origin',p.preview_view.summary.text()
    first_target=p.preview_view.plan['target'][:]
    p.generate_target_preview()
    deadline=time.monotonic()+10
    while p.preview_view.busy and time.monotonic()<deadline:pump(.03)
    assert p.preview_view.plan['purpose']=='origin' and p.preview_view.plan['target']==first_target
    p.control_scroll.ensureWidgetVisible(p.preview_source);pump(.2)
    main.grab().save(str(out/'精简流程_回原点目标来源.png'))
    circle=main.workbench.open_page('circle');circle.demo();pump(.3)
    assert circle.result and '合成' in circle.status.text()
    main.grab().save(str(out/'精简流程_圆孔离线任务.png'))
    events=main.workbench.open_page('events');events.refresh(True);pump(.2)
    assert events.table.rowCount()>0
    main.grab().save(str(out/'精简流程_运行日志.png'))
    configs=main.workbench.open_page('configs');pump(.2)
    assert main.workbench.settings_tier=='高级工具'
    main.workbench.open_page('wall');pump(.1);assert main.workbench.settings_tier=='常用设置'
    main.workbench.open_page('configs');pump(.1)
    assert main.workbench.group_nav.currentText()=='设置'
    main.grab().save(str(out/'精简流程_配置版本.png'))
    from PySide6.QtTest import QTest
    with patch.object(p.controller,'request_stop') as stop:
        main.activateWindow();pump(.15);QTest.keyClick(main,Qt.Key_Escape);pump(.1)
        assert stop.call_count==1,stop.call_args_list
    main.workbench.open_page('control');pump(.15)
    with patch.object(p.controller,'request_stop') as stop:
        main.activateWindow();pump(.15);QTest.keyClick(main,Qt.Key_Escape);pump(.1)
        assert stop.call_count==1,stop.call_args_list
    checks.append('origin intent survives generic re-preview with coincident input, task table, grouped navigation, circle demo, history/config pages, global Esc requests only Stop')
    main.close();pump();assert not errors,errors
    checks.append('shutdown cleans up pages and timers')
print(json.dumps(dict(checks=checks,errors=errors,hardware_connected=False,robot_moved=False,fixture_path=str(fixture)),ensure_ascii=False))
