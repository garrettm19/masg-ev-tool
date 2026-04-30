@echo off

echo Starting backend...
start cmd /k "cd backend && .venv\Scripts\activate && uvicorn main:app --reload --port 8000"

timeout /t 2 >nul

echo Starting frontend...
start cmd /k "cd frontend && npm run dev"

echo.
echo Both services starting...
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
pause
