# 라돈 CSV/TXT 파싱

`ktl_selectors.radon`은 업로드의 파일명과 바이트를 받아 파싱한다.
`parse_radon_upload`는 JSON 직렬화 가능한 dict를, `parse_radon_file`은 내부 계산용 dataclass를 반환한다.
추가 패키지는 필요 없다. 파일 저장, 네트워크 호출, 정렬, 병합, 선별 및 RAW 출력은 하지 않는다.
기존 Selector 계약은 유지하며, `REGISTRY`의 `radon_merge`는 아래 파싱 엔진을 호출한다.

```python
from ktl_selectors.radon import parse_radon_upload

payload = parse_radon_upload(filename="upload.txt", content=file_bytes)
# FastAPI에서 file_bytes = await upload.read() 로 얻은 bytes를 그대로 전달한다.
# payload를 응답으로 반환하거나 json.dumps(payload)로 직렬화할 수 있다.
```

경로를 가진 기존 호출자는 `parse_radon_path(path)`를 사용할 수 있다.
이는 파일을 읽어 `parse_radon_file(filename, content)`에 전달하는 래퍼다.
두 함수의 dataclass는 `to_dict()`로 JSON 응답과 동일한 구조로 변환한다.
`detect_radon_file(filename, content)`는 검증된 형식·모델·장비번호·건수의 dict를 반환하며,
미지원 또는 손상 파일은 `None`이다. 상세 오류를 표시할 때는 `parse_radon_file`을 호출한다.
파일 확장자는 `.csv`/`.txt`를 허용하고 실제 파서 분기는 파일 내용으로 결정한다.
입력 파일명이나 특정 예제 경로로 장비번호·모델·역할을 추측하지 않는다.

| 형식 | 식별 및 측정 구조 | 확인한 예제 |
|---|---|---|
| 챔버 | 설명문 뒤 필수 5개 열, 쉼표 구분 | CSV 1개, 24행 |
| FRD400 | MODEL NAME + S/N, 열 이름 없는 6개 필드, 점 날짜 | CSV 1개·TXT 2개, 각 22행 |
| FRD500 | MODEL NAME + SN, Date&Time/Radon 열 | CSV 2개·TXT 8개, 각 22행 |
| FRD2400V1 | MODEL NAME + SN, DT/Rn-222, 행 끝 탭 | TXT 1개, 23행 |

현재 합성 예제 총 15개는 CSV 4개·TXT 11개다. 업무 입력 조건은 기준 3개(CSV 1개·TXT 2개)와
시험품 1~12개이며, 이 단일 파일 파서는 입력 묶음의 역할이나 개수를 판단하지 않는다.
FRD500은 기준과 시험 양쪽에 쓰이므로 모델명만으로 역할을 결정할 수 없다.

반환값의 `format`은 `chamber` 또는 `device`, `file_type`은 입력 확장자다.
`measurement_count`는 실제 읽은 건수이며, `data_no`는 장비 파일에 선언된 건수다.
장비에는 `model_name`, `serial_number`, `measurement_start`, `measurement_end`, `unit`이 포함된다.
메타데이터 원문은 `metadata_lines`에 보존한다.

- 챔버 `columns`는 필수 5개 열을 원본 열 순서대로 제공한다. 각 측정행은
  `date`, `sequence_status`, `target_radon`, `calculate_radon`, `crm1_radon`을 제공한다.
  추가 열은 `extra_values`에 보존한다. Start/Source Purge/Zero Air Purge도 모두 유지한다.
- 장비 측정행은 `index`, `timestamp`, `radon`, `temp`, `humi`, `barometer`를 제공한다.
- 모든 측정행은 입력 순서와 원본 행 번호 `line`을 유지한다. 원문은
  `date_raw`/`timestamp_raw`와 `raw_values`로 제공하며 숫자는 유한 `float`로 변환한다.
- 날짜는 `YYYY-MM-DD HH:MM:SS`와 `YYYY.MM.DD HH:MM:SS`를 허용한다.
  시간대 정보가 없는 입력에 시간대를 부여하지 않는다.
- 기본 인코딩은 UTF-8(BOM 허용)이다. 다른 인코딩이 확인된 호출자는
  `encoding="cp949"`처럼 명시한다. 자동 추측이나 오류 문자 삭제는 하지 않는다.

해석 불가능한 날짜·숫자, 누락된 필수 메타데이터/열, 모르는 모델, 잘못된 행 구조는
`RadonParseError` (`ktl_contract.ReadError`의 하위 타입)를 발생시킨다.
`source_file`, `code`, `line`, `reason` 및 한국어 메시지를 제공한다.
빈 숫자 셀은 `None`과 `MISSING_VALUE` 경고를 반환하며 값을 채우지 않는다.
`Data No` 불일치는 `COUNT_MISMATCH` 경고를 반환하고 실제 측정행을 보존한다.
`warnings`는 계약 `Warning`을 확장하여 파일명과 행 번호를 포함한다.

## 서버의 Selector 호출

```python
from ktl_selectors import get_selector

selector = get_selector("radon_merge", fake_fallback=False)
detected = selector.detect(uploaded_path)
frame = selector.series([uploaded_path])
```

서버에 이미 파일 경로가 있으면 위 인터페이스를 사용한다. 저장하지 않은 업로드는
앞의 `parse_radon_upload(filename, content)`를 직접 호출한다.
`detect()`는 OpenAPI `DataFile.detected`에 맞춰 `kind`, `rows`와 확인 가능한
`serial`, `unit`, `interval_s`를 반환한다. `kind`는 `radon_chamber`, `radon_frd400`,
`radon_frd500`, `radon_frd2400` 중 하나다. `rows`는 실제 측정행 수이며,
간격은 입력 순서의 모든 시간 차이가 같은 양의 정수 초일 때만 제공한다.
모르는 형식·손상된 내용은 `None`, 파일 읽기 실패는 `ReadError`다.
상세 파싱 오류가 필요하면 `parse_radon_path()`를 호출한다.

`series()`는 `t`(datetime)와 숫자 채널의 DataFrame을 반환한다.
챔버 채널은 `target_radon`, `calculate_radon`, `crm1_radon`, 장비 채널은
`radon`, `temp`, `humi`, `barometer`다. 모든 입력 행의 순서를 유지한다.
Sequence Status와 원본 표기는 파싱 객체에서 조회할 수 있다.
여러 파일은 입력 순서대로 행을 이어 붙이고 채널에 `source_1.`, `source_2.` 등을 붙인다.
다른 파일의 채널과 빈 측정값은 `None`이며, 시간 정렬이나 장비 간 대응은 수행하지 않는다.
`source_N`은 호출 내 순번으로 서버의 file ID가 아니다.
`frame.attrs["sources"]`에 파일·장비·채널 정보, `frame.attrs["warnings"]`에 파싱 경고가 있다.
각 source의 `unit`은 파일에 선언된 라돈 단위이며 온도·습도·기압 단위를 뜻하지 않는다.
HTTP 응답은 서버가 datetime을 ISO 문자열로 직렬화하고 필요한 속성을 명시적으로 전달해야 한다.

2026-10-25 확인한 field-server의 `app/modules.py`는 아직 `FakeSelector`를 반환한다.
B-1에서 해당 로더가 위 패키지의 `get_selector()`를 호출하도록 연결해야 한다.
이 저장소의 테스트는 패키지 로더 → 실제 Selector → 파서를 검증하며,
실제 HTTP 업로드 연동을 검증한 것은 아니다. 업로드 엔드포인트 구현은 포함하지 않는다.

`run()`의 RAW 배치·병합은 별도 이슈 #13 범위다. 현재 호출하면 `ReadError`의 하위 타입인
`RadonMergePendingError`를 발생시킨다. 가짜 결과를 성공으로 반환하지 않는다.
따라서 `run()` 성공까지 요구하는 전체 계약 테스트는 아직 완료되지 않았다.
해당 테스트는 이 예외에만 strict xfail을 적용하며, 다른 실패는 그대로 실패 처리한다.
`detect()`와 `series()`는 별도의 정상·오류·원본 불변 테스트로 검증한다.

## 테스트

저장소 루트에서 실행한다. 기본 테스트는 `selection/synthetic/radon_parser/`의 작은 합성 파일을
사용한다. `radon_merge/` 예제가 있으면 15개 파일도 검증한다. 외부 예제 검증은 환경변수로
활성화하며, 지정하지 않으면 해당 테스트만 건너뛴다. 파일을 재생성하거나 수정하지 않는다.
동일한 파일의 경로/bytes 결과 일치와 bytes 파싱 중 파일 접근이 없다는 것도 검증한다.

```powershell
$env:RADON_EXAMPLE_DIR = 'D:\Tak\ktl-field-modules-feat-8-gl240\selection\synthetic\radon_merge'
.\.venv\Scripts\python.exe -m pytest -q contract readers selection
```

TODO(확인 필요): FRD400/FRD500 실제 CSV 출력 구조. 현재 지원 CSV는 제공된 합성 변형이다.
TODO(확인 필요): 챔버 단위와 `-99` 의미, 기준 장비와 CRM 채널의 관계, FRD400 3day 집계 정의.
이 정보는 추정하지 않고 원문으로 보존한다. 병합·단위 변환·집계는 다음 단계에서 다룬다.
