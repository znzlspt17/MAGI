"""여러 테스트에서 공유하는 검증용 도우미."""



def account(access, subject):
    sid = access.login(subject, "fake-test-pepper")
    return sid, access.session(sid)
