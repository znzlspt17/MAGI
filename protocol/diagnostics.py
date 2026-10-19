"""입력 원문과 로컬 변수를 제외한 공통 traceback 위치 정보."""


def traceback_frames(exc: BaseException) -> list[dict[str, object]]:
    frames = []
    traceback = exc.__traceback__
    while traceback is not None and len(frames) < 12:
        code = traceback.tb_frame.f_code
        frames.append({"filename": code.co_filename, "function": code.co_name,
                       "lineno": traceback.tb_lineno})
        traceback = traceback.tb_next
    return frames
