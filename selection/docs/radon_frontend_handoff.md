# 프론트 요청사항 — 라돈 파일 업로드부터 CSV 다운로드까지

제출 범위는 **ktl-field-modules#13의 B-4 모듈**이다. 이 문서는 B-1/B-2에 전달할 연동 요청사항이며 서버 API 구현·배포 완료 문서가 아니다.
서버 엔드포인트 구현과 CSV 파일 저장/다운로드는 B-1, 드래그 앤 드롭 화면은 B-2 담당이다. 별도 서버 PR을 #13의 필수 제출물로 요구하지 않는다.
서버 담당자는 설치한 `ktl_selectors`의 `detect(path)`, `series(paths)`, `run(paths, options)`를 계약대로 호출하면 된다.
아래 API 주소는 공동 명세의 연결 목표다. B-1에서 구현 상태를 확인한 뒤 프론트를 연결한다.

## 화면 동작

1. 라돈 접수 건에서 CSV/TXT를 여러 개 드래그 앤 드롭하거나 파일 선택으로 추가한다.
2. 파일마다 업로드 진행 상태, 원본 파일명, 판별 모델/종류, 내부 S/N을 각각 보여 준다. 파일명과 S/N은 구분한다.
3. 기준장비는 KTL로 시작하는 파일, HJ로 시작하는 파일, 1023 챔버 CSV의 CRM-1 Radon이다. 기준 3개 + 시험품 1~12개를 안내한다. 묶음 개수 검증의 서버/화면 분담은 B-1/B-2에서 정한다.
4. 모든 업로드가 끝난 뒤 성공한 파일 ID로 병합을 요청한다. `detected: null`인 파일은 지원 형식 확인 안내를 표시하고 병합 목록에서 제외한다.
5. 병합 중 중복 요청을 막고 진행 상태를 표시한다. 완료되면 결과 표와 경고를 보여 준다.
6. CSV 내보내기를 요청하고 완료 후 다운로드 버튼을 활성화한다.

원본 파일명은 그대로 전송한다. KTL/HJ 접두어와 1023 챔버 이름은 현재 사용자가 확인한 기준장비 구분 규칙이다.
모델명이나 S/N 모양만으로 기준/시험 장비를 추측하지 않는다.

## 연결 주소와 개발 환경

관리 API 기본 주소: `http://127.0.0.1:8766/api/admin/v1`.
관리 API는 PC 로컬 접근만 허용한다. React 개발 서버는 `/api`를 위 관리 서버로 프록시하거나 배포 시 같은 출처에서 호출한다.
별도 출처에서 직접 호출해야 한다면 CORS 정책은 B-1 담당자와 협의한다.
휴대폰 API(:8765)로 이 요청을 보내지 않는다.

| 단계 | 요청 | 성공 응답 |
|---|---|---|
| 파일 한 개 업로드 | POST `/cases/{case_id}/files` | 201 DataFile |
| 원본 시계열 조회(선택) | GET `/files/{file_id}/series` | 200 columns/rows/unit |
| 병합 요청 | POST `/cases/{case_id}/merges` | 202 Merge |
| 병합 상태 조회 | GET `/merges/{merge_id}` | 200 Merge |
| CSV 내보내기 요청 | POST `/cases/{case_id}/exports` | 202 Export |
| 내보내기 상태 조회 | GET `/exports/{export_id}` | 200 Export |
| CSV 다운로드 | GET `/exports/{export_id}/download` | 200 파일 응답 |

위 경로에는 기본 주소의 `/api/admin/v1`이 앞에 붙는다. `case_id`는 기존 라돈 접수 건 ID를 사용한다.

## 업로드

공동 명세의 단일 파일 API에 맞춰 각 파일을 `FormData`의 `file` 필드로 전송한다. 배열 업로드가 필요하면 B-1과 별도로 협의한다.

```javascript
const form = new FormData();
form.append("file", file, file.name);
const response = await fetch(`/api/admin/v1/cases/${caseId}/files`, {
  method: "POST", body: form,
});
```

브라우저가 multipart boundary를 만들도록 Content-Type은 직접 지정하지 않는다.
파일별 결과의 `id`, `name`, `sha256`, `detected`를 저장한다. `detected`의 `serial`이 내부 S/N이며 없는 경우 빈칸으로 표시한다.
표시할 파일명은 업로드 응답의 `name`을 사용한다. 모델/형식은 `detected.kind`로 구분한다.

## 병합 요청과 결과

```json
{
  "selector": "radon_merge",
  "file_ids": ["file_reference", "file_subject"],
  "options": {"align": "hour", "stddev_ddof": 1}
}
```

예시 ID는 실제 업로드 응답의 ID로 바꾼다. 같은 접수 건의 ID만 넣고 같은 ID를 중복하지 않는다.
`reference`를 별도 선택할 때는 options에 선택한 `file_id`를 전달한다. 파일 경로는 프론트에서 만들지 않는다.
`align: hour`는 기본값이다. 같은 날짜의 23:00/23:04/23:21을 23:00 행에 놓고 날짜가 바뀌면 다른 행으로 둔다.
`align: sequence`는 파일별 선택 순번으로 배치하는 별도 방식이다.
`stddev_ddof: 1`은 표본(n−1, 현재 기본값), `0`은 모집단(n) 표준편차다. 최종 업무 기준은 확인이 필요하다.

202 응답은 접수된 상태다. 응답 ID로 약 1초 간격으로 상태를 조회하고, `queued/running` 동안 기다린다.
`done` 또는 `failed`에서 조회를 멈추고 화면 이탈 시 진행 중인 조회 요청도 정리한다.
`failed`이면 Merge의 `error`를 표시하고 완료 표로 처리하지 않는다.

`done`의 `table.columns`, `table.rows`를 그대로 표에 사용한다. 번호/열 순서를 다시 정렬하지 않는다.
기준장비는 KTL → HJ → CRM-1 Radon → 나머지 입력 순서다.
`meta.sources`는 같은 출력 순서이며 `source_file`, `serial_number`, `model_name`, `display_index`, `is_reference`를 별도로 제공한다.
`source_index`는 원래 입력 순번이다. `selected_timestamps`는 정시 변환 전 실제 측정시각이다.

화면에서 파일명/S/N 행까지 보여 줄 때는 `meta.csv_header_rows` 두 행을 칼럼 머리글 위에 표시한다.
셀은 텍스트로 렌더링한다. 빈값(null)은 빈칸으로 두고 0으로 바꾸지 않는다.
`warnings[].message`를 함께 표시한다. 현재 결과는 사용자 확인용 출력이며 RAW1~4 최종 배치와 다르다.

## CSV 생성과 다운로드

```json
{
  "kind": "merge_raw",
  "format": "csv",
  "encoding": "utf-8",
  "merge_id": "mg_completed",
  "include_photos": false
}
```

완료된 병합 ID로 요청한다. 인코딩은 UTF-8(BOM 포함) 또는 cp949를 지원하며 이 화면에서는 UTF-8을 권장한다.
내보내기도 202 이후 상태를 조회한다. `done`이 되면 `/exports/{id}/download`를 파일로 받는다.
download 응답을 JSON으로 해석하지 않는다. 링크 다운로드 또는 Blob 저장을 사용하고 응답의 Content-Disposition 파일명을 사용한다.
공동 명세의 Export 응답에는 실패 원인 문자열이 없으므로 `failed`이면 일반 실패 안내와 작업 ID를 표시한다.

실제 CSV 순서: 파일명 행 → S/N 행 → 측정시간/장비 번호 머리글 → 시간대별 값 → 평균 → 표준편차.
챔버의 S/N은 빈칸이며 데이터 열 이름은 CRM-1 Radon이다. 평균/표준편차는 장비별 기존 선택 12개 값으로 계산한다.
정시 정렬 때문에 빈 셀이 생겨도 0을 넣거나 화면에서 다시 평균을 계산하지 않는다.
B-1 요청사항: `Export.preview.columns/rows`에도 실제 CSV 상단 행부터 같은 순서로 제공해 다운로드와 화면이 일치하도록 한다.

## 오류와 인수 확인

HTTP 오류는 `{ "error": { "code", "message", "detail" } }` 형식이다. 400의 `detail.fields`가 있으면 해당 칸에 이유를 표시한다.
선택값 12개 미만, 선택값 누락, 같은 장비의 동일 시간대 중복, 미지원 구조/인코딩은 오류가 될 수 있다. 일부 파일을 조용히 버려 성공한 것으로 표시하지 않는다.

- 기준 3개 + 시험품 12개로 업로드 → 완료 표 → CSV 다운로드를 확인한다.
- 23:00/23:04/23:21이 같은 날짜의 23:00 행에 들어가는지 확인한다.
- 파일명 행과 S/N 행의 값이 해당 데이터 열과 맞는지, 챔버 S/N이 빈칸인지 확인한다.
- 누락된 시간대가 빈칸이며 마지막 두 행이 평균/표준편차인지 확인한다.
- 잘못된 파일, 병합 실패, 내보내기 실패를 정상 완료와 구분한다.

## 남은 범위

RAW1~4 배치·지시오차·반복성은 아직 미구현이다. 이 문서의 표준편차를 최종 반복성 판정으로 표시하지 않는다.
이 문서의 API 요청 예시는 연동을 위한 전달 사항이며 #13이 서버/프론트 구현까지 완료했다는 의미가 아니다.
모듈 PR #28의 최근접 시각 매칭/시계 차이 방식은 이 PR의 정시 묶음과 다르다. 화면에서 혼용하기 전에 PM과 연결 방식을 맞춘다.
실제 새 파일의 구조/인코딩 검증 및 표준편차 최종 업무 기준 확인이 필요하다.
