"""Flowmeter reader scaffold pending OCR integration."""

from ktl_contract import ReadError, ReadResult


class FlowmeterReader:
    name = "flowmeter"

    def read(self, image_path: str, item: str) -> ReadResult:
        try:
            with open(image_path, "rb") as image_file:
                if not image_file.read(1):
                    raise ReadError("이미지 파일이 비어 있습니다.")
        except OSError as exc:
            raise ReadError("이미지 파일을 읽을 수 없습니다.") from exc

        # TODO(확인 필요): OCR 엔진·버전과 defender/alicat 화면 사양을 확정한 뒤 판독을 구현한다.
        raise ReadError("유량계 판독 기능은 OCR 연동 후 사용할 수 있습니다.")
