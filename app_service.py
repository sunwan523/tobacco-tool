import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import sys
import os
import subprocess
import time

class AppService(win32serviceutil.ServiceFramework):
    _svc_name_ = "TobaccoToolService"
    _svc_display_name_ = "Tobacco Tool Service"
    _svc_description_ = "Tobacco Tool Streamlit Application Service"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        if self.process:
            try:
                self.process.terminate()
                time.sleep(1)
            except:
                pass

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        self.main()

    def main(self):
        os.chdir(r"d:\codex\tobacco-tool")
        
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["LANG"] = "zh_CN.UTF-8"
        env["LC_ALL"] = "zh_CN.UTF-8"
        env["PYTHONUNBUFFERED"] = "1"
        
        cmd = [
            r"C:\Users\sunwa\AppData\Local\Programs\Python\Python310\python.exe",
            "-m", "streamlit", "run", "streamlit_app.py", "--server.port", "8501"
        ]
        
        self.process = subprocess.Popen(cmd, env=env)
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(AppService)