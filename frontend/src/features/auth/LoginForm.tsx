// Adapted from shadcn/ui login-04 (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import { Card, CardContent } from "../../shared/ui/card";
import { VStack } from "@astryxdesign/core/VStack";
import { Button } from "../../shared/ui/button";
import { ArrowRightIcon, FileTextIcon, ChatCircleDotsIcon, SealCheckIcon, ScalesIcon } from "@phosphor-icons/react";
import "./login.css";

export function LoginForm({ available, notice }: { available: boolean; notice: string }) {
  return (
    <main className="login-page">
      <a className="brand" href="/"><span className="brand-mark"><ScalesIcon weight="duotone" size={25} aria-hidden /></span>MAGI</a>
      <Card className="login-card overflow-hidden p-0">
        <CardContent className="grid p-0 md:grid-cols-2">
          <section className="login-form-content">
            <h1>개발 요청을<br />명확한 명세로</h1>
            <p>만들고 싶은 것을 설명하세요.<br />필요한 질문을 확인하고 명세를 함께 정리합니다.</p>
            <VStack className="login-action" gap={3}>
              <p role="status">{notice || (available ? "Google 계정으로 작업 공간을 시작하세요." : "Google 로그인 설정이 준비되지 않았습니다. 운영자에게 문의하세요.")}</p>
              {available && <Button asChild size="lg" variant="default"><a href="/auth/google/start">Google로 로그인<ArrowRightIcon size={18} aria-hidden /></a></Button>}
              <p>MAGI는 개인 비용으로 운영되는 서비스입니다. 무분별한 사용으로 인한 AI 토큰 고갈을 방지하기 위해 Google 계정 로그인만 지원합니다.</p>
            </VStack>
            <p className="login-privacy">이름·이메일·사진은 요청하지 않습니다.<br />계정 구분용 식별 정보만 사용합니다.</p>
          </section>
          <aside className="login-visual" aria-label="MAGI 작업 흐름">
            <h2>명세가 만들어지는 과정</h2>
            <ol className="login-steps">
              <li><FileTextIcon aria-hidden />요청 작성</li>
              <li><ChatCircleDotsIcon aria-hidden />질문 답변</li>
              <li><FileTextIcon aria-hidden />명세 검토</li>
              <li><SealCheckIcon aria-hidden />최종 확정</li>
            </ol>
          </aside>
        </CardContent>
      </Card>
      <footer className="public-links"><a href="/privacy">정보 처리 안내</a><a href="/licenses">오픈소스 라이선스</a><a href="/research">연구 출처 및 적용 방식</a></footer>
    </main>
  );
}
