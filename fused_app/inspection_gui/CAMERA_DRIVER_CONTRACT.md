工业相机接入约定

尚未绑定具体厂家SDK，测试使用接口替身，不代表实机验证。

设备连接提供connect(settings)、disconnect()、is_connected()。采集提供start()、stop()、get_frame()。get_frame仅返回新采集的uint8 BGR三通道图像，暂无新帧返回None，方法必须设置SDK超时，禁止无限阻塞。调用register_device_backend("camera", backend)注册。

可选参数接口：parameter_capabilities={"exposure_us":[最小值,最大值],"gain_db":[最小值,最大值],"trigger_modes":["continuous","software","hardware"]}。仅填写实际支持模式，单位必须符合键名。get_parameters返回实际exposure_us、gain_db和trigger_mode，set_parameters接收同名参数并写入设备，失败抛异常或返回False。参数读写前停止采集，不以期望配置代替设备读回。

每次按拍摄按钮生成按日期分目录的无损PNG与同名JSON。保存信息包含原图SHA256、尺寸、电脑接收帧时间、相机连接配置及其来源、实际参数读回和可获得的附近时刻机械臂A位姿。该位姿不是硬同步曝光位姿。原图或信息保存失败时不进入检测，已经生成的原图保留。

仅配置相机不代表在线或完成标定。就绪检查不会凭连接成功开放实际机械臂运动。
