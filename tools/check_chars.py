"""JSONファイル内の全文字列要素を再帰的に表示・比較するスクリプト"""

import json
import os
import sys

import polars as pl


def collect_char_counts(data, path="", result=None):
    """JSON要素を再帰的に走査し、各パスの文字数を収集する。

    Args:
        data: JSONから読み込んだデータ（dict, list, str, etc.）
        path: 現在のキーパス
        result: 収集結果を格納する辞書

    Returns:
        dict: {パス: (文字数, 型情報)} の辞書
    """
    if result is None:
        result = {}

    if isinstance(data, dict):
        total = 0
        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key
            collect_char_counts(value, current_path, result)
            total += _total_chars(value)
        if path:
            result[path] = (total, "dict")
    elif isinstance(data, list):
        total = 0
        for i, item in enumerate(data):
            current_path = f"{path}[{i}]"
            collect_char_counts(item, current_path, result)
            total += _total_chars(item)
        result[path] = (total, f"list({len(data)}要素)")
    elif isinstance(data, str):
        result[path] = (len(data), "str")

    return result


def _total_chars(data):
    """データに含まれる全文字列の合計文字数を返す。"""
    if isinstance(data, str):
        return len(data)
    elif isinstance(data, dict):
        return sum(_total_chars(v) for v in data.values())
    elif isinstance(data, list):
        return sum(_total_chars(item) for item in data)
    return 0


def build_dataframe(json_files):
    """複数のJSONファイルから文字数のDataFrameを構築する。

    Args:
        json_files: JSONファイルパスのリスト

    Returns:
        pl.DataFrame: パス・型・各ファイルの文字数を列に持つDataFrame
    """
    all_counts = {}
    all_types = {}
    file_labels = []

    for json_file in json_files:
        abs_path = os.path.abspath(json_file)
        parent = os.path.dirname(abs_path)
        grandparent = os.path.dirname(parent)
        label = os.path.basename(grandparent)
        # 同名ディレクトリがある場合、さらに上の親ディレクトリ名を付加
        if label in file_labels:
            great_grandparent = os.path.basename(os.path.dirname(grandparent))
            label = f"{great_grandparent}/{label}"
        file_labels.append(label)

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        counts = collect_char_counts(data)
        all_counts[label] = {path: chars for path, (chars, _) in counts.items()}
        all_types[label] = {path: typ for path, (_, typ) in counts.items()}

    # 全パスを収集（出現順を維持）
    all_paths = []
    seen = set()
    for label in file_labels:
        for path in all_counts[label]:
            if path not in seen:
                all_paths.append(path)
                seen.add(path)

    # 型情報を収集
    types = []
    for path in all_paths:
        for label in file_labels:
            if path in all_types[label]:
                types.append(all_types[label][path])
                break
        else:
            types.append("")

    # DataFrameを構築
    df_data = {
        "パス": all_paths,
        "型": types,
    }
    for label in file_labels:
        df_data[label] = [all_counts[label].get(path) for path in all_paths]

    df = pl.DataFrame(df_data)

    # 複数ファイルの場合、全ファイルに値があるパスのみ残す
    if len(file_labels) > 1:
        filter_expr = pl.lit(True)
        for label in file_labels:
            filter_expr = filter_expr & pl.col(label).is_not_null()
        df = df.filter(filter_expr)

    # 複数ファイルの場合、最初のファイルを基準にした差分列を追加
    if len(file_labels) >= 2:
        base = file_labels[0]
        diff_cols = []
        for label in file_labels[1:]:
            diff_cols.append(
                (pl.col(label) - pl.col(base)).alias(f"差分({label})")
            )
        df = df.with_columns(diff_cols)

    return df


def main():
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  python check_chars.py <json_file>              # 単一ファイル", file=sys.stderr)
        print("  python check_chars.py <file1> <file2> [...]    # 複数ファイル比較", file=sys.stderr)
        sys.exit(1)

    json_files = sys.argv[1:]

    df = build_dataframe(json_files)

    # 表示設定
    with pl.Config(
        tbl_rows=-1,
        tbl_cols=-1,
        tbl_width_chars=200,
        fmt_str_lengths=60,
    ):
        print(df)


if __name__ == "__main__":
    main()
