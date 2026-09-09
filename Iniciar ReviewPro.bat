@echo off
rem Arranca a app ReviewPro Pipeline e abre o browser em http://localhost:8501
cd /d "%~dp0"
"C:\Users\francisca\AppData\Local\Programs\Python\Python312\python.exe" -m streamlit run "reviewpro_pipeline\app.py" --server.port 8501 --browser.gatherUsageStats false
pause
