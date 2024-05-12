from loguru import logger
from subprocess import run, PIPE
from fastapi import FastAPI, Request, applications
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from aiohttp import ClientSession
from ipaddress import ip_address

app = FastAPI()

session: ClientSession


def swagger_monkey_patch(*args, **kwargs):
    """
    Wrap the function which is generating the HTML for the /docs endpoint and
    overwrite the default values for the swagger js and css.
    """
    kwargs.pop('swagger_js_url', None)
    kwargs.pop('swagger_css_url', None)

    return get_swagger_ui_html(  # 以免中国大陆无法获取 js css, 以至无法加载页面
        *args, **kwargs,
        swagger_js_url="https://cdn.staticfile.org/swagger-ui/5.6.2/swagger-ui-bundle.min.js",
        swagger_css_url="https://cdn.staticfile.org/swagger-ui/5.6.2/swagger-ui.min.css")


# Actual monkey patch
applications.get_swagger_ui_html = swagger_monkey_patch


@app.on_event('startup')
def setup():
    global session
    session = ClientSession()


@app.on_event('shutdown')
async def close():
    if isinstance(session, ClientSession):
        await session.close()


class ApiResponse(JSONResponse):
    media_type = "application/json"

    def __init__(
            self, content: dict = None, status_code: int = 200, headers: dict[str, str] | None = None, background=None
    ):
        content = content if content is not None else {}

        super().__init__(
            content=content,
            status_code=content.get('code', status_code),
            headers=headers,
            background=background
        )


def get_ipaddress(request: Request):
    real_ip = request.headers.get('cf-connecting-ip')
    logger.debug('cf-connecting-ip: {}, Client IP: {}', real_ip, request.client.host)
    return ip_address(real_ip or request.client.host)


def decode(_bytes: bytes) -> str:
    try:
        return _bytes.decode('u8')
    except UnicodeDecodeError:
        return _bytes.decode('GBK')


def check_ffmpeg(command: str = 'ffmpeg'):
    process = run(f'{command} -version', shell=True, stdout=PIPE, stderr=PIPE)

    out_bytes = process.stdout or process.stderr
    out = decode(out_bytes)

    if process.returncode:
        raise RuntimeError(f'FFmpeg not found: {out}')

    return True  # 无需对 FFmpeg 版本有要求

    try:
        first_line = out.split('\n', 1)[0].lower()
        version = first_line.split(' copyright', 1)[0].replace('ffmpeg version ', '')
    except IndexError:
        raise RuntimeError('FFmpeg version not found')

    if '-' in version:
        logger.debug('Is year-month-day version, FFmpeg version string: {}', version)
        try:
            year, month, day = tuple(int(item) for item in version.split('-', 3)[:-1])
            logger.debug('FFmpeg version year: {}, mouth: {}, day: {}', year, month, day)
            if year < 2022:
                return RuntimeError('FFmpeg version too low, must be more than 2022 years or 6.0 version')

            logger.success('FFmpeg version is OK')
            return True
        except ValueError:
            raise RuntimeError('failed to match FFmpeg version')

    logger.debug('Is semantic version, FFmpeg version string: {}', version)
    try:
        mojar, minor, patch = tuple(int(item) for item in version.split('.', 3))
        logger.debug('FFmpeg version major: {}, minor: {}, patch: {}', mojar, minor, patch)
        if mojar <= 4:
            raise RuntimeError('FFmpeg version too low, must be more than 6.0 version or 2022 years')

        logger.success('FFmpeg version is OK')
        return True
    except ValueError:
        raise RuntimeError('failed to match FFmpeg version')
