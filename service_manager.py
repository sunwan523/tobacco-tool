import win32serviceutil
import win32service
import win32event
import win32api
import win32con
import servicemanager
import socket
import sys
import os
import subprocess
import threading

class StreamlitService(win32serviceutil.ServiceFramework):
    _svc_name_ = "TobaccoToolService"
    _svc_display_name_ = "烟草工具服务"
    _svc_description_ = "烟草工具 Streamlit 应用服务"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        if self.process:
            self.process.terminate()

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        self.main()

    def main(self):
        os.chdir("d:\\codex\\tobacco-tool")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["LANG"] = "zh_CN.UTF-8"
        env["LC_ALL"] = "zh_CN.UTF-8"
        env["PYTHONUNBUFFERED"] = "1"
        
        cmd = [
            "C:\\Users\\sunwa\\AppData\\Local\\Programs\\Python\\Python310\\python.exe",
            "-m", "streamlit", "run", "streamlit_app.py", "--server.port", "8501"
        ]
        
        self.process = subprocess.Popen(cmd, env=env)
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

def install_service():
    win32serviceutil.InstallService(
        None,
        StreamlitService._svc_name_,
        StreamlitService._svc_display_name_,
        startType=win32service.SERVICE_AUTO_START,
        description=StreamlitService._svc_description_
    )
    print(f"服务 '{StreamlitService._svc_display_name_}' 安装成功")

def uninstall_service():
    win32serviceutil.UninstallService(StreamlitService._svc_name_)
    print(f"服务 '{StreamlitService._svc_display_name_}' 卸载成功")

def start_service():
    win32serviceutil.StartService(StreamlitService._svc_name_)
    print(f"服务 '{StreamlitService._svc_display_name_}' 启动成功")

def stop_service():
    win32serviceutil.StopService(StreamlitService._svc_name_)
    print(f"服务 '{StreamlitService._svc_display_name_}' 停止成功")

def restart_service():
    stop_service()
    import time
    time.sleep(2)
    start_service()
    print(f"服务 '{StreamlitService._svc_display_name_}' 重启成功")

def status_service():
    try:
        status = win32serviceutil.QueryServiceStatus(StreamlitService._svc_name_)
        status_code = status[1]
        if status_code == win32service.SERVICE_RUNNING:
            print(f"服务 '{StreamlitService._svc_display_name_}' 正在运行")
        elif status_code == win32service.SERVICE_STOPPED:
            print(f"服务 '{StreamlitService._svc_display_name_}' 已停止")
        elif status_code == win32service.SERVICE_START_PENDING:
            print(f"服务 '{StreamlitService._svc_display_name_}' 正在启动")
        elif status_code == win32service.SERVICE_STOP_PENDING:
            print(f"服务 '{StreamlitService._svc_display_name_}' 正在停止")
        else:
            print(f"服务 '{StreamlitService._svc_display_name_}' 状态: {status_code}")
    except Exception as e:
        print(f"服务状态查询失败: {e}")

def main():
    if len(sys.argv) < 2:
        print("用法: service_manager.py [install|uninstall|start|stop|restart|status]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "install":
        install_service()
    elif command == "uninstall":
        uninstall_service()
    elif command == "start":
        start_service()
    elif command == "stop":
        stop_service()
    elif command == "restart":
        restart_service()
    elif command == "status":
        status_service()
    else:
        print(f"未知命令: {command}")
        sys.exit(1)

if __name__ == '__main__':
    main()