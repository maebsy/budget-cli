"""budget-cli: 표준 라이브러리만으로 만든 콘솔 가계부.

계층 구조 (위 → 아래로만 의존한다)

    cli.py          명령어 파싱, 대화형 입력, 화면 출력        (프레젠테이션)
    decorators.py   에러 변환 · 실행 로그 · 시간 측정         (공통 관심사)
    services.py     기능 로직: 추가/검색/요약/예산/카테고리…   (유스케이스)
    storage.py      JSONL 파일 읽기/쓰기, 원자적 교체          (영속성)
    models.py       Transaction 등 데이터 구조                (도메인)
"""

__version__ = "1.0.0"
