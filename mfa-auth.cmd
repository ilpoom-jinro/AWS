@echo off
set /p MFA_CODE=OTP 6자리 입력: 

set CREDS_JSON=%TEMP%\aws-mfa-creds.json
set CREDS_CMD=%TEMP%\aws-mfa-setenv.cmd

aws sts get-session-token ^
  --serial-number arn:aws:iam::218549830271:mfa/platform ^
  --token-code %MFA_CODE% ^
  --duration-seconds 43200 ^
  --output json > "%CREDS_JSON%"

if errorlevel 1 (
  echo MFA 인증 실패
  exit /b 1
)

powershell -NoProfile -Command "$c = Get-Content '%CREDS_JSON%' | ConvertFrom-Json; '@echo off' | Set-Content '%CREDS_CMD%'; 'set ""AWS_ACCESS_KEY_ID=' + $c.Credentials.AccessKeyId + '""' | Add-Content '%CREDS_CMD%'; 'set ""AWS_SECRET_ACCESS_KEY=' + $c.Credentials.SecretAccessKey + '""' | Add-Content '%CREDS_CMD%'; 'set ""AWS_SESSION_TOKEN=' + $c.Credentials.SessionToken + '""' | Add-Content '%CREDS_CMD%'"

call "%CREDS_CMD%"

del "%CREDS_JSON%" >nul 2>&1
del "%CREDS_CMD%" >nul 2>&1

echo.
echo MFA 인증 완료
aws configure list
aws sts get-caller-identity