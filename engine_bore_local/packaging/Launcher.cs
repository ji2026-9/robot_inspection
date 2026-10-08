using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher {
    [STAThread]
    static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, ".venv", "pythonw.exe");
        if (!File.Exists(python)) {
            MessageBox.Show("运行环境不完整，请重新安装。", "箱体孔检测");
            return;
        }
        try {
            ProcessStartInfo info = new ProcessStartInfo(python, "\"" + Path.Combine(root,"app.py") + "\"");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.EnvironmentVariables.Remove("PYTHONHOME");
            info.EnvironmentVariables.Remove("PYTHONPATH");
            Process.Start(info);
        } catch(Exception ex) {
            MessageBox.Show("启动失败："+ex.Message, "箱体孔检测");
        }
    }
}
