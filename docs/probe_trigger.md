# 测头 DI_1 只读监测与触发采点

入口：主界面「位置记录与手动任务」→「测头采点」。工作区打开并连接反馈时自动保存输入低→高边沿。这里只接收 30004 端口反馈，不写输出、不使能、不运动。

DI_1 按高电平触发配置，尚须用实际轻触与松开完成输入映射对照。DO_1 仅显示反馈状态，不提供控制开关。协议依据：Dobot-Arm/TCP-IP-Python-V4 官方 dobot_api.py 的 MyType，DigitalInputs uint64 位于字节 8，DigitalOutputs 位于字节 16。DI_1 使用输入最低位；现场对照成功前不视作已完成触发验收。
https://github.com/Dobot-Arm/TCP-IP-Python-V4/blob/main/dobot_api.py

触发边沿在每帧接收线程里识别，而非依赖约 200ms 的 UI 刷新。持续高电平只记一次，松开回低后可重新采点。连接初始为高、长时间反馈间断、坐标 / 工具配置变化或控制器时间倒退后，不凭空生成触发记录。

每条事件保存同一反馈帧的 TCP、关节角、用户 / 工具编号与偏移、控制器时间戳、PC 接收时间、前后反馈间隔和原始 I/O 位图。数据以单事件原子 JSON 文件保存在 inspection_app/data/probe_workspace/probe_triggers/。最近 100 条在界面显示，可导出全部记录。写入失败会显示并重试；损坏历史文件原样保留并报警。

记录不是硬件触发锁存坐标；第一帧收到的 DI 高状态未必等于物理接触的准确时刻。短于反馈周期的脉冲仍可能漏检。高电平变化也可能源自接收器错误，尚未独立监测 RMI-QE ERROR 线，故每条记录均标记 physical_contact_confirmed=false、controller_latched=false、calibration_sample_verified=false、hardware_executable=false。不可直接用于正式标定或测量精度认定。

接收队列保留最近 512 条事件，工作区定时落盘；队列溢出会告警。软件关闭或连接中断时不能继续采点。保持工作区打开直到所需记录已保存。

验证：47 项自动测试、15 项隔离反馈 GUI 检查通过；真实静态反馈已读取，DI=0、DO=1，工具 1、用户 0，未使能未运行。真实触发与复位验收结果另行记录，不以模拟测试代替。

修改前备份：E:\robot_project\_backup_probe_trigger_20261015。源码同步至本地仓库 software，尚未上传 GitHub。