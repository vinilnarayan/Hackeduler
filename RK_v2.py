# -- coding: utf-8 --

import re
import json
import copy
from burp import IBurpExtender
from burp import IHttpListener, IScannerCheck


class BurpExtender(IBurpExtender, IHttpListener, IScannerCheck):

    # Set to True only when you need to debug which payloads are sent.
    # Left False so Burp's output stays clean (only real findings are logged).
    VERBOSE = False

    # Update the specific scope pattern with a regular expression.
    SCOPE_PATTERN = r"https://jsonplaceholder\.typicode\.com/.*"

    # List of common SQL error indicators.
    COMMON_SQL_ERRORS = [
        "org.postgresql.util.psqlexception",
        "syntax error",
        "unterminated string literal",
        "sql exception",
        "query error",
        "database error",
        "invalid syntax",
        "runtime error",
        "mysql error",
        "postgres error",
        # Add more as needed
    ]

    def registerExtenderCallbacks(self, callbacks):
        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()
        self.helpers = callbacks.getHelpers()
        callbacks.setExtensionName("RK-AI-Error-V2")
        callbacks.registerHttpListener(self)
        self._stdout = callbacks.getStdout()
        self._stderr = callbacks.getStderr()
        self._scope_regex = re.compile(self.SCOPE_PATTERN)
        # Remember findings we've already reported so the same
        # URL + parameter + error isn't logged over and over.
        self._reported = set()

    def log(self, message):
        self._stdout.write(message + "\n")

    def debug(self, message):
        if self.VERBOSE:
            self._stdout.write(message + "\n")

    def processHttpMessage(self, tool_flag, message_is_request, message_info):
        if not message_is_request:
            return
        if tool_flag != self._callbacks.TOOL_PROXY:
            return

        request_info = self._helpers.analyzeRequest(message_info)
        request_url = request_info.getUrl()
        if self._scope_regex.match(request_url.toString()):
            return
        if request_info.getMethod() == "OPTIONS":
            return

        request = message_info.getRequest()
        request_info = self._helpers.analyzeRequest(request)

        # Get JSON body from the request
        body_offset = request_info.getBodyOffset()
        body_bytes = request[body_offset:]
        body = self._helpers.bytesToString(body_bytes)

        # Parse JSON body
        try:
            json_body = json.loads(body)
        except ValueError:
            # Unable to parse JSON body
            return

        url_str = request_url.toString()
        for key_path, modified_body in self.inject_sqli_iteratively(json_body):
            param = self.format_key_path(key_path)
            test_body = json.dumps(modified_body)
            self.debug("[*] Testing " + url_str + " param=" + param)

            test_request = self._helpers.buildHttpMessage(
                request_info.getHeaders(),
                self._helpers.stringToBytes(test_body),
            )
            test_response = self._callbacks.makeHttpRequest(
                message_info.getHttpService(), test_request
            )
            raw_response = test_response.getResponse()
            if raw_response is None:
                continue
            response_body = self._helpers.bytesToString(raw_response).lower()

            # Report the first matching error for this parameter, then move on.
            for error in self.COMMON_SQL_ERRORS:
                if error in response_body:
                    self.report_finding(url_str, param, error)
                    break

    def report_finding(self, url_str, param, error):
        key = (url_str, param, error)
        if key in self._reported:
            return
        self._reported.add(key)
        self.log(
            "[!] Possible SQL Injection | URL: " + url_str +
            " | param: " + param +
            " | error: " + error
        )

    def format_key_path(self, key_path):
        return ".".join(str(k) for k in key_path)

    def inject_sqli_iteratively(self, data):
        # Yields (key_path, modified_body) so findings can name the parameter.
        for keys in self.get_all_keys(data):
            modified_data = copy.deepcopy(data)
            self.modify_json(modified_data, keys, "'")
            yield keys, modified_data

    def get_all_keys(self, data, parent_key=None):
        if parent_key is None:
            parent_key = []
        key_paths = []
        if isinstance(data, dict):
            for key, value in data.items():
                new_key = parent_key + [key]
                if isinstance(value, (dict, list)):
                    key_paths.extend(self.get_all_keys(value, new_key))
                else:
                    key_paths.append(new_key)
        elif isinstance(data, list):
            for index, value in enumerate(data):
                new_key = parent_key + [index]
                if isinstance(value, (dict, list)):
                    key_paths.extend(self.get_all_keys(value, new_key))
                else:
                    key_paths.append(new_key)
        return key_paths

    def modify_json(self, data, keys, injection):
        if len(keys) == 1:
            if isinstance(data[keys[0]], str):
                data[keys[0]] += injection
            else:
                data[keys[0]] = str(data[keys[0]]) + injection
        else:
            self.modify_json(data[keys[0]], keys[1:], injection)
