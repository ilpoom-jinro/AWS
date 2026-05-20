@echo off
set /p MFA_CODE=OTP 6자리 입력: 

aws sts get-session-token ^
  --serial-number arn:aws:iam::218549830271:mfa/AWS_platform ^
  --token-code %MFA_CODE% ^
  --duration-seconds 43200 ^
  --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" ^
  --output text > "%TEMP%\aws-mfa-creds.txt"

for /f "tokens=1,2,3" %%A in (%TEMP%\aws-mfa-creds.txt) do (
  set AWS_ACCESS_KEY_ID=%%A
  set AWS_SECRET_ACCESS_KEY=%%B
  set AWS_SESSION_TOKEN=%%C
)

del "%TEMP%\aws-mfa-creds.txt"

echo.
echo MFA 인증 완료
echo AWS_ACCESS_KEY_ID=%AWS_ACCESS_KEY_ID%
echo AWS_SESSION_TOKEN 설정됨
aws configure list
aws sts get-caller-identity