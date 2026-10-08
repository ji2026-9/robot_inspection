本机检测软件独立快照

该目录保留本机软件代码，未覆盖仓库原有app目录。
Release附件解压到本目录。models.zip和database_seed.zip对应可迁移的现用模型与28张标注数据，active_models.json使用相对路径。
其他附件保留原始数据和历史实验，可能包含旧机器绝对路径，属于归档资料。
不包含Python环境、安装包和临时缓存。runtime_versions.json列出依赖版本。
入口：python app.py。运行需先安装对应依赖。
当前支持图像孔检测与像素圆心，三维定位与机械臂自动测量尚未完成。
