@echo off
set /p MFA_CODE=OTP 6자리 입력: 

aws sts get-session-token ^
  --serial-number arn:aws:iam::218549830271:mfa/AWS_platform ^
  --token-code %MFA_CODE% ^
  --output json > "%TEMP%\aws-mfa-creds.json"

for /f "usebackq delims=" %%i in (`python -c "import json; print(json.load(open(r'%TEMP%\aws-mfa-creds.json'))['Credentials']['AccessKeyId'])"`) do set AWS_ACCESS_KEY_ID=%%i
for /f "usebackq delims=" %%i in (`python -c "import json; print(json.load(open(r'%TEMP%\aws-mfa-creds.json'))['Credentials']['SecretAccessKey'])"`) do set AWS_SECRET_ACCESS_KEY=%%i
for /f "usebackq delims=" %%i in (`python -c "import json; print(json.load(open(r'%TEMP%\aws-mfa-creds.json'))['Credentials']['SessionToken'])"`) do set AWS_SESSION_TOKEN=%%i

del "%TEMP%\aws-mfa-creds.json"

echo MFA 인증 완료
aws sts get-caller-identity