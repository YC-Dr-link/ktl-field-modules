"""업로드 파일명과 바이트를 받는 순수 파싱 API (파일 저장·병합 없음)."""
from pathlib import Path
import re

from ._radon_chamber import parse_chamber
from ._radon_device import parse_device
from .radon_models import ParsedRadonFile, RadonParseError

__all__ = ["parse_radon_file", "parse_radon_path", "parse_radon_upload", "detect_radon_file",
           "ParsedRadonFile", "RadonParseError"]


def parse_radon_file(filename: str, content: bytes, *,
                     encoding: str = "utf-8-sig") -> ParsedRadonFile:
    """CSV/TXT 내용을 판별한다. 인코딩을 추측하거나 오류 문자를 버리지 않는다.

    기본은 UTF-8(BOM 유무 모두 허용). 다른 인코딩을 알고 있는 호출자는
    encoding을 지정한다. 날짜는 파일의 지역 시각을 보존하는 naive datetime이다.
    """
    file_type = Path(filename).suffix.lower().lstrip(".")
    if file_type not in {"csv", "txt"}:
        raise RadonParseError(filename, "UNSUPPORTED_EXTENSION", "CSV 또는 TXT 파일이 필요합니다.")
    if not isinstance(content, bytes):
        raise RadonParseError(filename, "INVALID_INPUT", "content는 파일의 bytes여야 합니다.")
    try:
        text = content.decode(encoding)
    except UnicodeDecodeError as exc:
        line = content[:exc.start].count(b"\n") + 1
        raise RadonParseError(filename, "INVALID_ENCODING", f"{encoding} 인코딩으로 읽을 수 없습니다.", line) from exc
    except LookupError as exc:
        raise RadonParseError(filename, "INVALID_ENCODING", f"지원하지 않는 인코딩입니다: {encoding}") from exc
    text = text.removeprefix("\ufeff")
    if "\x00" in text:
        raise RadonParseError(filename, "INVALID_ENCODING", "NUL 문자가 있습니다. 파일 인코딩을 확인하세요.", text[:text.index("\x00")].count("\n") + 1)
    if not text.strip():
        raise RadonParseError(filename, "NO_DATA", "파일에 측정 데이터가 없습니다.")
    # 확장자·파일명의 장비번호가 아니라 내용의 모델 선언으로 장비 파일을 분기.
    if re.search(r"^\s*(?:MODEL\s+NAME\s*:|(?:FTLAB|FRD2400)\s+RADON\s+DATA\s+FILE)", text, re.I | re.M):
        return parse_device(filename, text, file_type)
    return parse_chamber(filename, text, file_type)


def parse_radon_path(path: str, *, encoding: str = "utf-8-sig") -> ParsedRadonFile:
    """기존 경로 기반 호출자를 위한 읽기 전용 어댑터."""
    source = Path(path)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise RadonParseError(source.name, "FILE_READ_ERROR", "파일을 읽을 수 없습니다.") from exc
    return parse_radon_file(source.name, content, encoding=encoding)


def parse_radon_upload(filename: str, content: bytes, *, encoding: str = "utf-8-sig") -> dict:
    """UploadFile.read()의 bytes를 받아 JSON으로 바로 반환할 수 있는 dict.

    FastAPI 종속성·임시 파일 없이 동작한다. 내부 계산에는 parse_radon_file의
    datetime/숫자 dataclass를 사용하고 웹 응답에는 이 함수를 사용한다.
    """
    return parse_radon_file(filename, content, encoding=encoding).to_dict()


def detect_radon_file(filename: str, content: bytes, *, encoding: str = "utf-8-sig") -> dict | None:
    """파싱·유효성 검증된 형식 요약. 미지원/손상 파일은 None.

    자세한 오류 및 경고가 필요한 호출자는 parse_radon_file을 사용한다.
    기준/시험 장비 역할은 파일 형식만으로 추정하지 않는다.
    """
    try:
        result = parse_radon_file(filename, content, encoding=encoding)
    except RadonParseError:
        return None
    return {"format": result.format, "file_type": result.file_type,
            "model_name": result.model_name, "serial_number": result.serial_number,
            "measurement_count": result.measurement_count}
