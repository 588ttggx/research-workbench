"""报告式核对：比较改前/改后正文的数字、引用、链接和限定句，只报告不改写。

用法：
    python 写作修订核对.py 改前.md 改后.md [--json 输出.json]

报告输出不得与任一输入指向同一文件；失败保留输入原稿及已有报告。
退出码 0 表示报告生成成功；文件缺失、路径冲突或写入失败返回 2。命中不代表必须改，
只把“删掉了什么”摆出来，由作者逐条确认。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

BOLD = re.compile(r'\*\*|__')
SPACE = re.compile(r'\s+')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
NUMBER = re.compile(r'\d+(?:\.\d+)?%?')
CITATION = re.compile(
    r'\[[0-9]{1,3}(?:\s*[-,–]\s*[0-9]{1,3})*\]'
    r'|10\.\d{4,9}/[^\s)\]，。；、]+'
    r'|\b(?:oa-[0-9a-f]{6,}|PMC\d+|group-[0-9a-f]{4,})\b'
)
LINK = re.compile(r'\]\(([^)\s]+)\)')
SENTENCE = re.compile(r'[^。！？!?\n|]+[。！？!?]?')
QUALIFIER = re.compile(
    '不能|未能|尚未|未测|未取得|未完成|不保证|不提供|不足以|无法|不声称|不代表|不等同'
    '|不建议|不用于|仅|只|可能|或许|提示|初步|摘要级|外推|待核|假设|估计'
)


def load(path: Path) -> str:
    return path.read_text('utf-8-sig')


def normalize(text: str) -> str:
    text = BOLD.sub('', text)
    text = text.replace('\u3000', ' ')
    return SPACE.sub(' ', text).strip()


def numbers(text: str) -> Counter:
    clean = CITATION.sub(' ', normalize(text))
    clean = DATE.sub(' ', clean)
    return Counter(NUMBER.findall(clean))


def dates(text: str) -> Counter:
    return Counter(DATE.findall(normalize(text)))


def citations(text: str) -> Counter:
    return Counter(CITATION.findall(normalize(text)))


def links(text: str) -> Counter:
    return Counter(LINK.findall(normalize(text)))


def sentences(text: str) -> list[str]:
    text = BOLD.sub('', text).replace('\u3000', ' ')
    rows = []
    for raw in SENTENCE.findall(text):
        row = SPACE.sub(' ', raw).strip().strip('|').strip()
        if row:
            rows.append(row)
    return rows


def qualifier_sentences(text: str) -> list[str]:
    return [row for row in sentences(text) if QUALIFIER.search(row)]


def removed(before: Counter, after: Counter) -> dict:
    return {key: before[key] - after[key] for key in sorted(before) if before[key] > after[key]}


def added(before: Counter, after: Counter) -> dict:
    return {key: after[key] - before[key] for key in sorted(after) if after[key] > before[key]}


def compare(before_text: str, after_text: str) -> dict:
    before_sentences = Counter(sentences(before_text))
    after_sentences = Counter(sentences(after_text))
    lost_qualifiers = [
        row for row in qualifier_sentences(before_text)
        if before_sentences[row] > after_sentences.get(row, 0)
    ]
    new_qualifiers = [
        row for row in qualifier_sentences(after_text)
        if after_sentences[row] > before_sentences.get(row, 0)
    ]
    return {
        'numbers_removed': removed(numbers(before_text), numbers(after_text)),
        'numbers_added': added(numbers(before_text), numbers(after_text)),
        'dates_removed': removed(dates(before_text), dates(after_text)),
        'dates_added': added(dates(before_text), dates(after_text)),
        'citations_removed': removed(citations(before_text), citations(after_text)),
        'citations_added': added(citations(before_text), citations(after_text)),
        'links_removed': removed(links(before_text), links(after_text)),
        'links_added': added(links(before_text), links(after_text)),
        'lost_qualifier_sentences': lost_qualifiers,
        'new_qualifier_sentences': new_qualifiers,
    }


def markdown(result: dict) -> str:
    lines = ['# 写作修订核对', '']
    lines.append(f"- 数字：删除 {len(result['numbers_removed'])} 类，新增 {len(result['numbers_added'])} 类")
    lines.append(f"- 日期：删除 {len(result['dates_removed'])} 类，新增 {len(result['dates_added'])} 类")
    lines.append(f"- 引用：删除 {len(result['citations_removed'])} 类，新增 {len(result['citations_added'])} 类")
    lines.append(f"- 链接：删除 {len(result['links_removed'])} 类，新增 {len(result['links_added'])} 类")
    lines.append(f"- 删除的限定句：{len(result['lost_qualifier_sentences'])} 句")

    def block(title, rows):
        lines.extend(['', f'## {title}', ''])
        if not rows:
            lines.append('无。')
            return
        for row in rows:
            lines.append(f'- {row}')

    block('删除的数字', [f'{key}（{value} 次）' for key, value in result['numbers_removed'].items()])
    block('删除的日期', [f'{key}（{value} 次）' for key, value in result['dates_removed'].items()])
    block('删除的引用', [f'{key}（{value} 次）' for key, value in result['citations_removed'].items()])
    block('删除的链接', [f'{key}（{value} 次）' for key, value in result['links_removed'].items()])
    block('删除的限定句（逐条确认）', result['lost_qualifier_sentences'])
    block('新增的限定句', result['new_qualifier_sentences'])
    lines.extend(['', '命中只说明文字变了，不等于必须保留；必要的证据边界请按“删掉会不会误导”判断。', ''])
    return '\n'.join(lines)


def write_json(path: Path, payload: dict, *, protected_paths: tuple[Path, ...]) -> None:
    resolved = path.resolve()
    for source in protected_paths:
        if resolved == source.resolve() or (path.exists() and path.samefile(source)):
            raise ValueError('JSON 报告不能覆盖改前或改后原稿，包括同文件的路径别名。')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.' + path.name + '.',
                                         suffix='.tmp', delete=False) as output:
            temp = Path(output.name)
            json.dump(payload, output, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='比较改前/改后正文的数字、引用、链接和限定句，只报告不改写。')
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--json', type=Path, dest='json_path')
    args = parser.parse_args(argv)
    if not args.before.is_file() or not args.after.is_file():
        print('改前或改后文件不存在。', file=sys.stderr)
        return 2
    try:
        result = compare(load(args.before), load(args.after))
        if args.json_path:
            write_json(args.json_path, result, protected_paths=(args.before, args.after))
    except (OSError, ValueError) as error:
        print('核对报告未保存：' + str(error), file=sys.stderr)
        return 2
    print(markdown(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
