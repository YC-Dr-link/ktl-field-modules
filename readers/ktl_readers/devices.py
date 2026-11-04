"""기기 프로필: 화면 사진에서 기기를 알아보고, 화면 크롭이 맞는지 대조하는 글자 목록.

새 기기 등록 = 아래 PROFILES에 한 덩어리 추가. 코드는 고치지 않는다.
  id      : 이 기기라고 알아보는 글자 (로고, 화면에 늘 뜨는 제목)
  screen  : 화면 '안'에 있어야 하는 글자 → 크롭 밖에 있으면 크롭을 넓혀 넣는다
  outside : 화면 '밖'에 있는 글자 (로고·버튼 이름) → 넓혔더니 들어오면 넓히기를 취소한다
글자는 소문자·띄어쓰기 없이 적는다. 're:'로 시작하면 정규식.
대조되는 기기가 없으면 기본 크롭을 그대로 쓴다 (사람이 최종 확인·수정).
"""

PROFILES: dict[str, dict[str, list[str]]] = {
    "defender510": {
        "id": ["defender510", "contmeasurement"],
        "screen": ["contmeasurement", "flow:", "avg:", "of003", "pause", "reset"],
        "outside": ["defender510", "enter"],
    },
    "alicat": {
        "id": ["alicat", "voluflow", "batterypowered"],
        "screen": ["torr", "tare", "voluflow", "slpm", "lpm", "next"],
        "outside": ["alicat", "batterypowered", "portableinstrument", "scientific"],
    },
    "bam1020": {
        "id": ["calibrationmode", "refmbrn", "calmass", "calibratesetup", "spancheck", "selectday", "qtot"],
        "screen": ["calibrationmode", "refmbrn", "count", "calmass", "calibratesetup", "spancheck", "conc",
                   "qtot", "start", "stop", "exit", "next", "prev", "selectday", "flowrate", r"re:^\d{2}/\d{2}/\d{2}"],
        "outside": ["current", "average", "error", "recall", "transfer", "module", "monitor"],
    },
    "mezus610": {
        "id": ["mezus610", "particulatemonitor", "pmanalyzer"],
        "screen": ["running", "stop", "spantest", "pmanalyzer", "count", "mg/cm2", r"re:\d{4}-\d{2}-\d{2}"],
        "outside": ["mezus610", "particulatemonitor"],
    },
}
