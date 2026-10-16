"""Offline, full-pose IK for the display model. No device or network APIs.

The numerical joint envelope is a preview constraint, NOT controller limits.
No collision, physical calibration, velocity or acceleration certification.
"""
import copy
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from .offline_planning import robot_frames
from .readonly_kinematics import pose_matrix
from .probe_workspace import vector6

PREVIEW_LIMITS_DEG = np.array([[-360., 360.]] * 6)
POSITION_TOL_MM = .5
ANGLE_TOL_DEG = .25
MAX_STEP_DEG = 12.


def tcp_matrix(joints, tool):
    return robot_frames(joints, (0, 0, 0))['flange'] @ tool


def compile_joint_preview(frames, tool_offset, seed_deg=None, cancelled=None, progress=None):
    """Solve each Cartesian sample continuously; stop at first invalid sample.

    Output contains only verified display-model samples. Failed frames are never
    rendered with invented joint angles. Seed is radians internally, deg in JSON.
    """
    tool = pose_matrix(vector6(tool_offset, '预览工具偏移'))
    seed = np.deg2rad(vector6(seed_deg if seed_deg is not None else
                            [130, -50, 100, 40, 90, 0], '起点关节角'))
    lower, upper = np.deg2rad(PREVIEW_LIMITS_DEG.T)
    if np.any(seed < lower) or np.any(seed > upper):
        raise ValueError('起点关节角超出软件预览范围 ±360°；这不是控制器限位')
    if not frames or len(frames) > 2500:
        raise ValueError('轨迹采样数量无效，最多 2500 帧')
    solved = []
    report = dict(total_frames=len(frames), solved_frames=0, complete=False,
                  failure=None, max_position_mm=0., max_orientation_deg=0.,
                  max_joint_step_deg=0., near_singular_frames=[],
                  joint_envelope_deg=PREVIEW_LIMITS_DEG.tolist(),
                  controller_limits_verified=False, collision_verified=False,
                  hardware_executable=False, model_only=True)
    for i, frame in enumerate(frames):
        if cancelled and cancelled():
            return [], {'cancelled': True}
        tip = np.asarray(frame['tip'], float)
        rot = np.asarray(frame['rotation'], float)
        if (tip.shape != (3,) or rot.shape != (3, 3) or not np.isfinite(tip).all()
                or not np.isfinite(rot).all() or
                not np.allclose(rot.T @ rot, np.eye(3), atol=1e-6) or
                not np.isclose(np.linalg.det(rot), 1., atol=1e-6)):
            raise ValueError('轨迹位姿不是有效的刚体变换')

        def residual(q):
            if cancelled and cancelled():
                raise InterruptedError('预览计算已取消')
            actual = tcp_matrix(q, tool)
            angle = Rotation.from_matrix(actual[:3, :3] @ rot.T).as_rotvec()
            return np.r_[actual[:3, 3] - tip, angle * 150.]

        # Continuation on previous solution preserves the branch. Do not jump
        # to a remote solution just to make an unreachable path look successful.
        fit = least_squares(residual, np.clip(seed, lower+1e-9, upper-1e-9),
                            bounds=(lower, upper), max_nfev=65,
                            ftol=1e-7, xtol=1e-7, gtol=1e-7)
        err = residual(fit.x)
        pe = float(np.linalg.norm(err[:3]))
        ae = float(np.rad2deg(np.linalg.norm(err[3:]) / 150.))
        step = float(np.max(np.abs(np.rad2deg(fit.x - seed))))
        reason = ('目标位姿无满足精度的连续逆解（可能不可达或超出预览范围）'
                  if pe > POSITION_TOL_MM or ae > ANGLE_TOL_DEG else
                  '相邻采样关节变化超过 12°，停止以避免姿态跳变'
                  if step > MAX_STEP_DEG and (i > 0 or seed_deg is not None) else '')
        if reason:
            report['failure'] = dict(frame_index=i, stage=frame['stage'], reason=reason,
                                     position_mm=pe, orientation_deg=ae, joint_step_deg=step,
                                     tip_mm=tip.tolist())
            break
        singular = np.linalg.svd(fit.jac, compute_uv=False)
        if singular[-1] / max(singular[0], 1e-9) < 1e-4:
            report['near_singular_frames'].append(i)
        item = copy.deepcopy(frame)
        item.update(joints=fit.x.copy(), ik_valid=True, position_error_mm=pe,
                    orientation_error_deg=ae)
        solved.append(item)
        seed = fit.x
        report['max_position_mm'] = max(report['max_position_mm'], pe)
        report['max_orientation_deg'] = max(report['max_orientation_deg'], ae)
        report['max_joint_step_deg'] = max(report['max_joint_step_deg'], step)
        if progress and (i % 12 == 0 or i == len(frames)-1):
            progress(i+1, len(frames))
    report['solved_frames'] = len(solved)
    report['complete'] = len(solved) == len(frames)
    return solved, report
