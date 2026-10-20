import { StrictMode } from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { Markdown } from "./UI";
afterEach(cleanup);
it("목차 링크는 StrictMode 재렌더에서도 실제 제목과 일치한다", () => {
  const content =
    "# Title\n\n## First\n\n```md\n## Code example\n```\n\n### Second";
  const view = render(
    <StrictMode>
      <Markdown content={content} />
    </StrictMode>,
  );
  const check = () => {
    for (const title of ["First", "Second"]) {
      const heading = screen.getByRole("heading", { name: title }),
        link = screen.getByRole("link", { name: title });
      expect(link.getAttribute("href")).toBe("#" + heading.id);
    }
    expect(screen.queryByRole("link", { name: "Code example" })).toBeNull();
  };
  check();
  const ids = screen.getAllByRole("heading").map((heading) => heading.id);
  view.rerender(
    <StrictMode>
      <Markdown content={content} />
    </StrictMode>,
  );
  check();
  expect(screen.getAllByRole("heading").map((heading) => heading.id)).toEqual(
    ids,
  );
});
it("실제 Markdown 제목만 수집하고 인라인 서식과 중첩 제목을 반영한다", () => {
  const content = [
    "## **Strong** and `code` with [link](https://example.com) &amp; ![image](image.png) ##",
    "",
    "Setext title",
    "------------",
    "",
    "> ### Quoted title",
    "",
    "- ### List title",
    "",
    "~~~md",
    "## Fenced title",
    "~~~",
    "",
    "    ## Indented code",
    "",
    "\\## Escaped title",
    "",
    "<div>",
    "## HTML sample",
    "</div>",
    "",
    "##No space",
  ].join("\n");
  const { container } = render(<Markdown content={content} />);
  const toc = container.querySelector(".document-toc")!;
  const links = within(toc as HTMLElement).getAllByRole("link");
  expect(links.map((link) => link.textContent)).toEqual([
    "Strong and code with link & image",
    "Setext title",
    "Quoted title",
    "List title",
  ]);
  for (const link of links) {
    const id = link.getAttribute("href")!.slice(1);
    const heading = document.getElementById(id)!;
    expect(["H2", "H3"]).toContain(heading.tagName);
  }
});
it("동시에 표시한 문서는 같은 제목과 줄 번호여도 고유한 링크 대상을 갖는다", () => {
  const view = render(
    <StrictMode>
      <Markdown content={"## Same\n\n### Same"} />
      <Markdown content={"## Same\n\n### Same"} />
    </StrictMode>,
  );
  const articles = view.container.querySelectorAll("article");
  const ids = Array.from(
    view.container.querySelectorAll("h2,h3"),
    (heading) => heading.id,
  );
  expect(new Set(ids).size).toBe(4);
  for (const article of articles) {
    for (const link of article.querySelectorAll(".document-toc a")) {
      const target = document.getElementById(
        link.getAttribute("href")!.slice(1),
      );
      expect(article.contains(target)).toBe(true);
    }
  }
});
it("제목 없는 문서는 목차를 숨기고 내용 변경 후 새 제목을 연결한다", () => {
  const view = render(<Markdown content={"```md\n## Sample\n```"} />);
  expect(view.container.querySelector(".document-toc")).toBeNull();
  view.rerender(<Markdown content={"Text\n\n## Updated"} />);
  const heading = screen.getByRole("heading", { name: "Updated" });
  expect(
    screen.getByRole("link", { name: "Updated" }).getAttribute("href"),
  ).toBe("#" + heading.id);
});
