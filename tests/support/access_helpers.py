"""여러 테스트에서 공유하는 검증용 도우미."""



async def account(access, subject):
    sid = await access.login(subject, "fake-test-pepper")
    return sid, await access.session(sid)
