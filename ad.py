import json


def extract_refresh_tokens():
    filename = 'data.json'

    try:
        # 1. 读取 JSON 文件 (指定 utf-8 编码防止乱码)
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 2. 处理数据结构
        # 情况 A: 如果文件里是一个列表 [...]，包含多个对象
        if isinstance(data, list):
            tokens = [item.get('refresh_token') for item in data if item.get('refresh_token')]

        # 情况 B: 如果文件里是单个对象 {...}
        elif isinstance(data, dict):
            tokens = [data.get('refresh_token')] if data.get('refresh_token') else []

        else:
            print("JSON 格式无法识别，请确保是对象或数组。")
            return

        # 3. 逐行打印结果
        if tokens:
            # 使用 \n 连接列表并一次性打印，效率更高
            print('\n'.join(tokens))
        else:
            print("未找到 refresh_token 字段。")

    except FileNotFoundError:
        print(f"错误: 找不到文件 '{filename}'，请确认文件已保存。")
    except json.JSONDecodeError:
        print(f"错误: '{filename}' 不是有效的 JSON 格式。")


if __name__ == "__main__":
    extract_refresh_tokens()