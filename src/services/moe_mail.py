"""
自定义域名邮箱服务实现
基于 email.md 中的 REST API 接口
"""

import re
import time
import json
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

from .base import BaseEmailService, EmailServiceError, EmailServiceType
from ..core.http_client import HTTPClient, RequestConfig
from ..config.constants import OTP_CODE_PATTERN

logger = logging.getLogger(__name__)


class MeoMailEmailService(BaseEmailService):
    """
    自定义域名邮箱服务
    基于 REST API 接口
    """

    def __init__(self, config: Dict[str, Any] = None, name: str = None):
        """
        初始化自定义域名邮箱服务

        Args:
            config: 配置字典，支持以下键:
                - base_url: API 基础地址 (必需)
                - api_key: API 密钥 (必需)
                - api_key_header: API 密钥请求头名称 (默认: X-API-Key)
                - timeout: 请求超时时间 (默认: 30)
                - max_retries: 最大重试次数 (默认: 3)
                - proxy_url: 代理 URL
                - default_domain: 默认域名
                - default_expiry: 默认过期时间（毫秒）
            name: 服务名称
        """
        super().__init__(EmailServiceType.MOE_MAIL, name)

        # 必需配置检查
        required_keys = ["base_url", "api_key"]
        missing_keys = [key for key in required_keys if key not in (config or {})]

        if missing_keys:
            raise ValueError(f"缺少必需配置: {missing_keys}")

        # 默认配置
        default_config = {
            "base_url": "",
            "api_key": "",
            "api_key_header": "X-API-Key",
            "timeout": 30,
            "max_retries": 10,
            "proxy_url": None,
            "default_domain": None,
            "default_expiry": 3600000,  # 1小时
        }

        self.config = {**default_config, **(config or {})}

        # 创建 HTTP 客户端
        http_config = RequestConfig(
            timeout=self.config["timeout"],
            max_retries=self.config["max_retries"],
        )
        self.http_client = HTTPClient(
            proxy_url=self.config.get("proxy_url"),
            config=http_config
        )

        # 状态变量
        self._emails_cache: Dict[str, Dict[str, Any]] = {}
        self._last_config_check: float = 0
        self._cached_config: Optional[Dict[str, Any]] = None

    def _get_headers(self) -> Dict[str, str]:
        """获取 API 请求头"""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # 添加 API 密钥
        api_key_header = self.config.get("api_key_header", "X-API-Key")
        headers[api_key_header] = self.config["api_key"]

        return headers

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        发送 API 请求

        Args:
            method: HTTP 方法
            endpoint: API 端点
            **kwargs: 请求参数

        Returns:
            响应 JSON 数据

        Raises:
            EmailServiceError: 请求失败
        """
        url = urljoin(self.config["base_url"], endpoint)

        # 添加默认请求头
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(self._get_headers())

        try:
            # POST 请求禁用自动重定向，手动处理以保持 POST 方法（避免 HTTP→HTTPS 重定向时被转为 GET）
            if method.upper() == "POST":
                kwargs["allow_redirects"] = False
                response = self.http_client.request(method, url, **kwargs)
                # 处理重定向
                max_redirects = 5
                redirect_count = 0
                while response.status_code in (301, 302, 303, 307, 308) and redirect_count < max_redirects:
                    location = response.headers.get("Location", "")
                    if not location:
                        break
                    import urllib.parse as _urlparse
                    redirect_url = _urlparse.urljoin(url, location)
                    # 307/308 保持 POST，其余（301/302/303）转为 GET
                    if response.status_code in (307, 308):
                        redirect_method = method
                        redirect_kwargs = kwargs
                    else:
                        redirect_method = "GET"
                        # GET 不传 body
                        redirect_kwargs = {k: v for k, v in kwargs.items() if k not in ("json", "data")}
                    response = self.http_client.request(redirect_method, redirect_url, **redirect_kwargs)
                    url = redirect_url
                    redirect_count += 1
            else:
                response = self.http_client.request(method, url, **kwargs)

            if response.status_code >= 400:
                error_msg = f"API 请求失败: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = f"{error_msg} - {error_data}"
                except:
                    error_msg = f"{error_msg} - {response.text[:200]}"

                self.update_status(False, EmailServiceError(error_msg))
                raise EmailServiceError(error_msg)

            # 解析响应
            try:
                data = response.json()
                if isinstance(data, dict) and "success" in data and not data["success"]:
                    error_msg = f"API 业务失败: {data.get('message', '')} (Code: {data.get('code', '')})"
                    raise EmailServiceError(error_msg)
                return data
            except json.JSONDecodeError:
                return {"raw_response": response.text}

        except Exception as e:
            self.update_status(False, e)
            if isinstance(e, EmailServiceError):
                raise
            raise EmailServiceError(f"API 请求失败: {method} {endpoint} - {e}")

    def get_config(self, force_refresh: bool = False) -> Dict[str, Any]:
        """获取系统配置（用于获取可用域名）"""
        if not force_refresh and self._cached_config and time.time() - self._last_config_check < 300:
            return self._cached_config

        try:
            response = self._make_request("GET", "/api/mailbox/domains")
            domains = response.get("data", [])
            self._cached_config = {"emailDomains": ",".join(domains)}
            self._last_config_check = time.time()
            self.update_status(True)
            return self._cached_config
        except Exception as e:
            logger.warning(f"获取配置失败: {e}")
            return {}

    def create_email(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """创建临时邮箱"""
        # 获取默认配置
        sys_config = self.get_config()
        default_domain = self.config.get("default_domain")
        if not default_domain and sys_config.get("emailDomains"):
            domains = sys_config["emailDomains"].split(",")
            default_domain = domains[0].strip() if domains else None

        request_config = config or {}
        create_data = {}
        if request_config.get("domain") or default_domain:
            create_data["domain"] = request_config.get("domain") or default_domain
        if request_config.get("name"):
            create_data["local_part"] = request_config.get("name")

        try:
            response = self._make_request("POST", "/api/mailbox/create", json=create_data)
            data = response.get("data", {})
            email = data.get("address", "").strip()

            if not email:
                raise EmailServiceError("API 返回数据不完整")

            email_info = {
                "email": email,
                "service_id": email,
                "id": email,
                "created_at": time.time(),
                "expire_at": data.get("expire_at"),
                "raw_response": response,
            }

            self._emails_cache[email] = email_info

            logger.info(f"成功创建临时邮箱: {email}")
            self.update_status(True)
            return email_info

        except Exception as e:
            self.update_status(False, e)
            if isinstance(e, EmailServiceError):
                raise
            raise EmailServiceError(f"创建邮箱失败: {e}")

    def get_verification_code(
            self,
            email: str,
            email_id: str = None,
            timeout: int = 120,
            pattern: str = OTP_CODE_PATTERN,
            otp_sent_at: Optional[float] = None,
    ) -> Optional[str]:
        """从临时邮箱列表接口获取验证码"""
        import urllib.parse

        logger.info(f"正在从临时邮箱 {email} 获取验证码...")

        start_time = time.time()
        seen_message_ids = set()
        address_encoded = urllib.parse.quote(email)

        while time.time() - start_time < timeout:
            try:
                # 使用邮箱列表接口
                response = self._make_request("GET", f"/api/emails/{address_encoded}?page=1&limit=20")
                data = response.get("data", {})
                messages = data.get("emails", []) if data else []

                if not isinstance(messages, list):
                    time.sleep(3)
                    continue

                for message in messages:
                    message_id = str(message.get("id"))
                    if not message_id or message_id in seen_message_ids:
                        continue

                    seen_message_ids.add(message_id)

                    sender = str(message.get("from", "")).lower()
                    subject = str(message.get("subject", ""))
                    content = str(message.get("text_body", ""))
                    if not content:
                        content = str(message.get("html_body", ""))

                    full_content = f"{sender} {subject} {content}"

                    if "openai" not in sender and "openai" not in full_content.lower():
                        continue

                    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                    match = re.search(pattern, re.sub(email_pattern, "", full_content))
                    if match:
                        code = match.group(1)
                        logger.info(f"从临时邮箱 {email} 找到验证码: {code}")
                        self.update_status(True)
                        return code

            except Exception as e:
                logger.debug(f"检查邮件时出错: {e}")

            time.sleep(3)

        logger.warning(f"等待验证码超时: {email}")
        return None

    def _get_message_content(self, email_id: str, message_id: str) -> Optional[str]:
        """获取邮件内容"""
        try:
            response = self._make_request("GET", f"/api/email/{message_id}")
            message = response.get("data", {})
            content = str(message.get("text_body", ""))
            if not content:
                html = str(message.get("html_body", ""))
                if html:
                    content = re.sub(r"<[^>]+>", " ", html)
            return content
        except Exception as e:
            logger.debug(f"获取邮件内容失败: {e}")
            return None

    def list_emails(self, cursor: str = None, **kwargs) -> List[Dict[str, Any]]:
        """
        列出所有邮箱

        Args:
            cursor: 分页游标
            **kwargs: 其他参数

        Returns:
            邮箱列表
        """
        params = {}
        if cursor:
            params["cursor"] = cursor

        try:
            response = self._make_request("GET", "/api/emails", params=params)
            emails = response.get("emails", [])

            # 更新缓存
            for email_info in emails:
                email_id = email_info.get("id")
                if email_id:
                    self._emails_cache[email_id] = email_info

            self.update_status(True)
            return emails
        except Exception as e:
            logger.warning(f"列出邮箱失败: {e}")
            self.update_status(False, e)
            return []

    def delete_email(self, email_id: str) -> bool:
        """
        删除邮箱

        Args:
            email_id: 邮箱 ID

        Returns:
            是否删除成功
        """
        try:
            response = self._make_request("DELETE", f"/api/emails/{email_id}")
            success = response.get("success", False)

            if success:
                # 从缓存中移除
                self._emails_cache.pop(email_id, None)
                logger.info(f"成功删除邮箱: {email_id}")
            else:
                logger.warning(f"删除邮箱失败: {email_id}")

            self.update_status(success)
            return success

        except Exception as e:
            logger.error(f"删除邮箱失败: {email_id} - {e}")
            self.update_status(False, e)
            return False

    def check_health(self) -> bool:
        """检查自定义域名邮箱服务是否可用"""
        try:
            # 尝试获取配置
            config = self.get_config(force_refresh=True)
            if config:
                logger.debug(f"自定义域名邮箱服务健康检查通过，配置: {config.get('defaultRole', 'N/A')}")
                self.update_status(True)
                return True
            else:
                logger.warning("自定义域名邮箱服务健康检查失败：获取配置为空")
                self.update_status(False, EmailServiceError("获取配置为空"))
                return False
        except Exception as e:
            logger.warning(f"自定义域名邮箱服务健康检查失败: {e}")
            self.update_status(False, e)
            return False

    def get_email_messages(self, email_id: str, cursor: str = None) -> List[Dict[str, Any]]:
        """
        获取邮箱中的邮件列表

        Args:
            email_id: 邮箱 ID
            cursor: 分页游标

        Returns:
            邮件列表
        """
        params = {}
        if cursor:
            params["cursor"] = cursor

        try:
            response = self._make_request("GET", f"/api/emails/{email_id}", params=params)
            messages = response.get("messages", [])
            self.update_status(True)
            return messages
        except Exception as e:
            logger.error(f"获取邮件列表失败: {email_id} - {e}")
            self.update_status(False, e)
            return []

    def get_message_detail(self, email_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        """
        获取邮件详情

        Args:
            email_id: 邮箱 ID
            message_id: 邮件 ID

        Returns:
            邮件详情
        """
        try:
            response = self._make_request("GET", f"/api/emails/{email_id}/{message_id}")
            message = response.get("message")
            self.update_status(True)
            return message
        except Exception as e:
            logger.error(f"获取邮件详情失败: {email_id}/{message_id} - {e}")
            self.update_status(False, e)
            return None

    def create_email_share(self, email_id: str, expires_in: int = 86400000) -> Optional[Dict[str, Any]]:
        """
        创建邮箱分享链接

        Args:
            email_id: 邮箱 ID
            expires_in: 有效期（毫秒）

        Returns:
            分享信息
        """
        try:
            response = self._make_request(
                "POST",
                f"/api/emails/{email_id}/share",
                json={"expiresIn": expires_in}
            )
            self.update_status(True)
            return response
        except Exception as e:
            logger.error(f"创建邮箱分享链接失败: {email_id} - {e}")
            self.update_status(False, e)
            return None

    def create_message_share(
            self,
            email_id: str,
            message_id: str,
            expires_in: int = 86400000
    ) -> Optional[Dict[str, Any]]:
        """
        创建邮件分享链接

        Args:
            email_id: 邮箱 ID
            message_id: 邮件 ID
            expires_in: 有效期（毫秒）

        Returns:
            分享信息
        """
        try:
            response = self._make_request(
                "POST",
                f"/api/emails/{email_id}/messages/{message_id}/share",
                json={"expiresIn": expires_in}
            )
            self.update_status(True)
            return response
        except Exception as e:
            logger.error(f"创建邮件分享链接失败: {email_id}/{message_id} - {e}")
            self.update_status(False, e)
            return None

    def get_service_info(self) -> Dict[str, Any]:
        """获取服务信息"""
        config = self.get_config()
        return {
            "service_type": self.service_type.value,
            "name": self.name,
            "base_url": self.config["base_url"],
            "default_domain": self.config.get("default_domain"),
            "system_config": config,
            "cached_emails_count": len(self._emails_cache),
            "status": self.status.value,
        }