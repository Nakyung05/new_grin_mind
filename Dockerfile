# --- 1단계: Flutter 앱 빌드 ---
# Flutter SDK가 설치된 이미지를 'build'라는 별명으로 사용합니다.
FROM leoafarias/flutter:3.19.6 as build
WORKDIR /app

# Flutter 프로젝트 파일들을 복사합니다.
COPY pubspec.* ./
COPY lib ./lib
COPY assets ./assets

# Flutter 의존성을 설치합니다.
RUN flutter pub get

# Flutter 앱을 웹 버전으로 빌드합니다.
# 이 결과로 /app/build/web 폴더가 생성됩니다.
RUN flutter build web


# --- 2단계: Python 서버 설정 및 최종 이미지 생성 ---
# 기존에 사용하던 Python 이미지를 사용합니다.
FROM python:3.10-slim

WORKDIR /app

# 환경 변수를 설정합니다.
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 서버 의존성을 설치합니다.
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 서버 코드를 복사합니다.
COPY server/ .

# --- 여기서가 핵심입니다! ---
# 1단계(build 스테이지)에서 생성된 Flutter 빌드 결과물을
# 현재 이미지의 /app/static/ 폴더로 복사합니다.
COPY --from=build /app/build/web ./static/

# 서버를 실행합니다.
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "app:app"]