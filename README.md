# ktl-field-modules — B-3 사진 판독 · B-4 선별·병합

| 폴더 | 패키지 | 담당 | 리뷰 짝 |
|---|---|---|---|
| `contract/` | `ktl_contract` — 계약 타입 · 가짜 모듈 · 계약 테스트 도우미 | PM (고치려면 ktl-hub 이슈) | — |
| `readers/` | `ktl_readers` — `cert` · `flowmeter` · `dust` | **지호 · 정윤** | 서로 |
| `selection/` | `ktl_selectors` — `gas_select` · `radon_merge` | **탁 · 다운** | 서로 |
| `categories.yaml` | 분류 · 촬영 항목 · 출력 칼럼 (B-1·B-2·B-3·B-4 공용) | 전원 (바꾸면 여준·희승 리뷰) | — |

| 기준 문서 | |
|---|---|
| 요구사항 | [REQ-B3](https://github.com/YC-Dr-link/ktl-hub/blob/main/docs/01-요구사항명세.md#6-b-3-사진-판독-모듈--지호--정윤) · [REQ-B4](https://github.com/YC-Dr-link/ktl-hub/blob/main/docs/01-요구사항명세.md#7-b-4-선별병합-모듈--탁--다운) |
| 계약 | [02 §3](https://github.com/YC-Dr-link/ktl-hub/blob/main/docs/02-API명세.md#3-모듈-계약-b-3--b-4--b-1) |

## 실행

```
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e contract -e readers -e selection pytest
pytest
```

## 규칙

- Reader/Selector는 **파일 경로만 받고 값만 돌려준다.** 네트워크 · DB · 저장 금지.
- 새 Reader/Selector는 `ktl_readers/__init__.py` · `selection/ktl_selectors/__init__.py`의 `REGISTRY`에 등록하고, `tests/`에 계약 테스트(`ktl_contract.testing`)를 추가한다.
- 테스트 이미지·파일은 가짜 값으로 만들어 `readers/synthetic/`, `selection/synthetic/`에만.
- 의존성 추가는 이슈로 (서버와 버전을 맞춰야 함).
