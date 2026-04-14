import json


def extract_credentials_from_list(input_file, output_file):
    try:
        # 1. 读取 JSON 文件
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 2. 获取 accounts 列表
        # 使用 .get() 安全获取，如果没有 accounts 字段则默认为空列表 []
        accounts_list = data.get('accounts', [])

        final_results = []

        # 3. 遍历列表中的每一个账户
        # 这里的 account 变量代表列表中的每一项（也就是那个包含 email, credentials 的字典）
        for account in accounts_list:
            # 确保当前项是字典类型，防止数据脏乱导致报错
            if isinstance(account, dict):
                # 提取 credentials 字段
                creds = account.get('credentials')

                # 如果 credentials 存在，就加入结果列表
                if creds:
                    final_results.append(creds)

        # 4. 检查结果
        if not final_results:
            print("⚠️ 警告: 未提取到任何数据，请检查 JSON 结构。")
            return

        # 5. 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            # indent=2 让输出格式美观，ensure_ascii=False 防止中文乱码
            json.dump(final_results, f, indent=2, ensure_ascii=False)

        print(f"✅ 提取成功！共处理 {len(final_results)} 个账户。")
        print(f"📄 结果已保存到: {output_file}")

    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 '{input_file}'")
    except json.JSONDecodeError:
        print(f"❌ 错误: JSON 格式无效，请检查文件内容。")
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")


# 运行配置
input_filename = 'kiro-accounts-2026-04-09.json'  # 你的源文件
output_filename = 'output_credentials.json'  # 目标文件

if __name__ == "__main__":
    extract_credentials_from_list(input_filename, output_filename)