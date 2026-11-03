// Adapted from shadcn/ui login-04 (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import { Card, CardContent } from "../../shared/ui/card";
import { Button } from "../../shared/ui/button";
import { ArrowRightIcon, FileTextIcon, ChatCircleDotsIcon, SealCheckIcon, ScalesIcon } from "@phosphor-icons/react";

export function LoginForm({ available, notice }: { available: boolean; notice: string }) {
  return (
    <main className="login-page">
      <a className="brand" href="/"><span className="brand-mark"><ScalesIcon weight="duotone" size={25} aria-hidden /></span>MAGI</a>
      <Card className="login-card overflow-hidden p-0">
        <CardContent className="grid p-0 md:grid-cols-2">
          <section className="login-form-content">
            <span className="eyebrow">YOUR IDEAS, CLEARLY DEFINED</span>
            <h1>좋은 아이디어의<br />다음 페이지.</h1>
            <p>막연했던 개발 요청을 구체화하고,<br />검토 가능한 명세로 완성하세요.</p>
            <div className="login-action">
              <p role="status">{notice || (available ? "Google 계정으로 작업 공간을 시작하세요." : "Google 로그인 설정이 준비되지 않았습니다. 운영자에게 문의하세요.")}</p>
              {available && <Button asChild size="lg"><a href="/auth/google/start">Google로 로그인<ArrowRightIcon size={18} aria-hidden /></a></Button>}
              <p>MAGI는 개인 비용으로 운영되는 서비스입니다. 무분별한 사용으로 인한 AI 토큰 고갈을 방지하기 위해 Google 계정 로그인만 지원합니다.</p>
            </div>
            <p className="login-privacy">이름·이메일·사진은 요청하지 않습니다.<br />계정 구분용 식별 정보만 사용합니다.</p>
          </section>
          <aside className="login-visual" aria-label="MAGI 작업 흐름">
            <span className="eyebrow">A LITTLE CLARITY GOES A LONG WAY</span>
            <div className="login-orbit"><ScalesIcon weight="duotone" size={86} aria-hidden /></div>
            <h2>생각을 나누고,<br />명확함을 쌓아갑니다.</h2>
            <ol className="login-steps">
              <li><ChatCircleDotsIcon weight="duotone" aria-hidden />요청과 대화</li>
              <li><FileTextIcon weight="duotone" aria-hidden />명세와 검토</li>
              <li><SealCheckIcon weight="duotone" aria-hidden />승인과 완성</li>
            </ol>
          </aside>
        </CardContent>
      </Card>
      <footer className="public-links"><a href="/privacy">정보 처리 안내</a><span>·</span><a href="/licenses">오픈소스 라이선스</a><a href="/research">연구 출처 및 적용 방식</a></footer>
    </main>
  );
}
