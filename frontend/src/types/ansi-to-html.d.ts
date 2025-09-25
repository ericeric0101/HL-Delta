// 注意：這個 .d.ts 檔不要有任何 import/export（保持全域宣告）
declare module 'ansi-to-html' {
  interface AnsiToHtmlOptions {
    fg?: string;
    bg?: string;
    newline?: boolean;
    escapeXML?: boolean;
    stream?: boolean;
    colors?: { [code: number]: string };
  }

  export default class AnsiToHtml {
    constructor(options?: AnsiToHtmlOptions);
    toHtml(input: string): string;
  }
}
