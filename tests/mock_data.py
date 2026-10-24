"""生成模拟的 Coverity CLI 输出（模拟一个嵌入式遥测固件项目）。"""
import json
from pathlib import Path


def generate(mock_dir: str) -> None:
    base = Path(mock_dir)
    (base / "asts").mkdir(parents=True, exist_ok=True)

    # cov-manage-emit list（自定义 JSON 适配格式）
    tus = {
        "translation_units": [
            {
                "id": 1,
                "primary_file": "src/telemetry/packet.c",
                "compiler": "iccxr32 (Green Hills XRay 2022.1)",
                "args": ["-g", "-O2", "-DUSE_CRC32", "-Isrc/include"],
                "source_files": ["src/telemetry/packet.c", "src/include/packet.h"],
            },
            {
                "id": 2,
                "primary_file": "src/telemetry/encode.c",
                "compiler": "iccxr32 (Green Hills XRay 2022.1)",
                "args": ["-g", "-O2", "-Isrc/include"],
                "source_files": ["src/telemetry/encode.c", "src/include/encode.h"],
            },
            {
                "id": 3,
                "primary_file": "src/rtos/task.c",
                "compiler": "iccxr32 (Green Hills XRay 2022.1)",
                "args": ["-g", "-Isrc/include", "-DRTOS_TICK=1000"],
                "source_files": ["src/rtos/task.c"],
            },
            {
                "id": 4,
                "primary_file": "src/driver/uart.c",
                "compiler": "iccxr32 (Green Hills XRay 2022.1)",
                "args": ["-g", "-O2", "-Isrc/include"],
                "source_files": ["src/driver/uart.c"],
            },
        ]
    }
    (base / "tus.json").write_text(json.dumps(tus, ensure_ascii=False, indent=1), "utf-8")

    # find '.*' --print-callees
    entities = {
        "entities": [
            {"name": "telemetry_main_task", "kind": "function", "file": "src/rtos/task.c", "line": 42, "definition": "src/rtos/task.c:42",
             "callees": ["read_uart_frame", "parse_packet", "encode_packet", "task_delay"]},
            {"name": "parse_packet", "kind": "function", "file": "src/telemetry/packet.c", "line": 88, "definition": "src/telemetry/packet.c:88",
             "callees": ["crc32_verify", "decode_header"]},
            {"name": "crc32_verify", "kind": "function", "file": "src/telemetry/packet.c", "line": 55, "definition": "src/telemetry/packet.c:55",
             "callees": ["crc32_table_lookup"]},
            {"name": "crc32_table_lookup", "kind": "function", "file": "src/telemetry/packet.c", "line": 30, "definition": "src/telemetry/packet.c:30",
             "callees": []},
            {"name": "decode_header", "kind": "function", "file": "src/telemetry/packet.c", "line": 70, "definition": "src/telemetry/packet.c:70",
             "callees": []},
            {"name": "encode_packet", "kind": "function", "file": "src/telemetry/encode.c", "line": 110, "definition": "src/telemetry/encode.c:110",
             "callees": ["crc32_append", "uart_write"]},
            {"name": "crc32_append", "kind": "function", "file": "src/telemetry/encode.c", "line": 80, "definition": "src/telemetry/encode.c:80",
             "callees": ["crc32_table_lookup"]},
            {"name": "read_uart_frame", "kind": "function", "file": "src/driver/uart.c", "line": 130, "definition": "src/driver/uart.c:130",
             "callees": ["uart_read_byte"]},
            {"name": "uart_read_byte", "kind": "function", "file": "src/driver/uart.c", "line": 60, "definition": "src/driver/uart.c:60",
             "callees": []},
            {"name": "uart_write", "kind": "function", "file": "src/driver/uart.c", "line": 95, "definition": "src/driver/uart.c:95",
             "callees": []},
            {"name": "task_delay", "kind": "function", "file": "src/rtos/task.c", "line": 12, "definition": "src/rtos/task.c:12",
             "callees": []},
            {"name": "g_packet_buffer", "kind": "variable", "file": "src/telemetry/packet.c", "line": 20, "definition": "src/telemetry/packet.c:20",
             "callees": []},
            {"name": "packet_header_t", "kind": "type", "file": "src/include/packet.h", "line": 15, "definition": "src/include/packet.h:15",
             "callees": []},
        ]
    }
    (base / "callees.json").write_text(json.dumps(entities, ensure_ascii=False, indent=1), "utf-8")

    # cov-format-errors --json-output-v10
    issues = {
        "format_version": "1.4",
        "issues": [
            {
                "cid": 1001,
                "checkerName": "NULL_RETURNS",
                "severity": "Major",
                "function": {"name": "parse_packet"},
                "file": [
                    {"file": "src/telemetry/packet.c", "line": 91, "description": "decode_header 可能返回 NULL"},
                    {"file": "src/telemetry/packet.c", "line": 93, "description": "未检查即解引用 hdr"},
                ],
            },
            {
                "cid": 1002,
                "checkerName": "MISSING_RETURN",
                "severity": "Warning",
                "function": {"name": "crc32_verify"},
                "file": [
                    {"file": "src/telemetry/packet.c", "line": 58, "description": "部分控制流路径缺少返回值"},
                ],
            },
            {
                "cid": 1003,
                "checkerName": "UNINIT.HEAP",
                "severity": "Major",
                "function": {"name": "encode_packet"},
                "file": [
                    {"file": "src/telemetry/encode.c", "line": 115, "description": "堆缓冲区未初始化即被 crc32_append 读取"},
                ],
            },
        ],
    }
    (base / "issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=1), "utf-8")

    # --print-codexm 函数 AST（CodeXM 模型简化样例）
    ast = {
        "name": "parse_packet",
        "kind": "functionDefinition",
        "location": {"file": "src/telemetry/packet.c", "line": 88},
        "formalParameterList": [{"kind": "localVariable", "identifier": "frame", "type": "const uint8_t *"}],
        "returnType": "packet_t *",
        "body": {
            "kind": "blockStatement",
            "children": [
                {"kind": "callExpression", "target": "decode_header"},
                {"kind": "callExpression", "target": "crc32_verify"},
                {"kind": "returnStatement"},
            ],
        },
    }
    (base / "asts" / "parse_packet.json").write_text(json.dumps(ast, ensure_ascii=False, indent=1), "utf-8")

    print(f"mock 输出已生成: {base}")


if __name__ == "__main__":
    import sys
    generate(sys.argv[1] if len(sys.argv) > 1 else "mock_idir")
