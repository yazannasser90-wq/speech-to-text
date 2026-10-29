# -*- coding: utf-8 -*-
"""
استخدام من سطر الأوامر (اختياري — للمستخدمين المتقدمين)

أمثلة:
  python cli.py lecture.mp3
  python cli.py interview.m4a -l ar -m medium -o out.txt
  python cli.py podcast.mp3 -l en --srt --translate ar
"""

import argparse
import sys

from transcriber import Transcriber, segments_to_srt


def main():
    parser = argparse.ArgumentParser(description="تحويل ملف صوتي إلى نص (عربي/إنجليزي)")
    parser.add_argument("audio", help="مسار الملف الصوتي")
    parser.add_argument("-l", "--language", default=None,
                        choices=["ar", "en", None],
                        help="لغة الكلام: ar أو en (الافتراضي: اكتشاف تلقائي)")
    parser.add_argument("-m", "--model", default="small",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="حجم النموذج (الافتراضي: small)")
    parser.add_argument("-o", "--output", default=None,
                        help="ملف لحفظ النص (الافتراضي: الطباعة على الشاشة)")
    parser.add_argument("--srt", action="store_true",
                        help="حفظ ملف ترجمة SRT بجانب النص")
    parser.add_argument("--translate", default=None, choices=["ar", "en"],
                        help="ترجمة النص بعد التفريغ إلى ar أو en")
    args = parser.parse_args()

    engine = Transcriber(args.model)
    print(f"تحميل نموذج {args.model} والتفريغ جارٍ... ", file=sys.stderr)
    result = engine.transcribe(
        args.audio, language=args.language,
        progress_callback=lambda r, s: print(f"\r{int(r*100)}%", end="", file=sys.stderr),
    )
    print("\n", file=sys.stderr)

    text = result["text"]
    if args.translate:
        import translator as tr
        print("ترجمة...", file=sys.stderr)
        text = tr.translate_text(text, target=args.translate)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"حُفظ النص في: {args.output}", file=sys.stderr)
    else:
        print(text)

    if args.srt:
        srt_path = (args.output or "output").rsplit(".", 1)[0] + ".srt"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(segments_to_srt(result["segments"]))
        print(f"حُفظت الترجمة الزمنية في: {srt_path}", file=sys.stderr)

    print(f"\nاللغة المكتشفة: {result['language']} "
          f"(ثقة {result['language_probability']:.0%}) — "
          f"المدة: {result['duration']:.1f} ثانية", file=sys.stderr)


if __name__ == "__main__":
    main()
