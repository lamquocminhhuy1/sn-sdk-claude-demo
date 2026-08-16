# CodeVault

Website Django cá nhân để lưu **screenshot**, **source code** và **file XML**, giúp chuyển dữ liệu từ máy công ty (bị chặn Claude) sang máy cá nhân để phân tích bằng Claude / Claude Code.

## Tính năng

- **Đăng nhập bắt buộc** — toàn bộ dữ liệu (kể cả file ảnh/XML) đều nằm sau login, không ai xem được nếu không có tài khoản.
- **Lưu screenshot**: paste trực tiếp từ clipboard (Ctrl+V) hoặc kéo-thả ảnh vào trang tạo mới — không cần lưu file ra desktop trước.
- **Lưu source code**: paste code, chọn ngôn ngữ, xem lại với nút **Copy** 1 click và chế độ **Raw** (text thuần) để copy nhanh vào Claude.
- **Lưu XML**: paste nội dung XML hoặc upload file `.xml` (update set, story export...), có nút Copy/Download.
- **Ghi chú kèm theo**: mỗi item có field Note để ghi sẵn câu hỏi/context định hỏi Claude.
- Tìm kiếm theo tiêu đề/nội dung/ghi chú, lọc theo loại, phân trang.
- Xoá item sẽ xoá luôn file trên disk (giữ quota 512 MB của bản free).

## Chạy local

```bash
cd codevault
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Mở http://127.0.0.1:8000 và đăng nhập bằng tài khoản vừa tạo.

## Deploy lên PythonAnywhere (bản Free)

Bản **free đủ dùng** cho mục đích này: 1 web app tại `<username>.pythonanywhere.com`, 512 MB disk, HTTPS sẵn. Chỉ cần lên bản Developer ($5) nếu bạn hết disk (nhiều screenshot) hoặc muốn web app không bị "sleep" (bản free phải bấm "Run until 3 months from today" mỗi 3 tháng).

### 1. Đưa code lên

Mở **Bash console** trên PythonAnywhere:

```bash
git clone https://github.com/lamquocminhhuy1/sn-sdk-claude-demo.git
cd sn-sdk-claude-demo/codevault
```

### 2. Tạo virtualenv và cài dependencies

```bash
mkvirtualenv codevault --python=python3.11
pip install -r requirements.txt
```

### 3. Khởi tạo database, tài khoản, static files

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --no-input
```

### 4. Tạo web app

Vào tab **Web** → **Add a new web app**:

- Chọn **Manual configuration** (KHÔNG chọn "Django" — mình tự cấu hình).
- Python version: **3.11**.
- **Source code**: `/home/<username>/sn-sdk-claude-demo/codevault`
- **Virtualenv**: `/home/<username>/.virtualenvs/codevault`

### 5. Sửa WSGI file

Trong tab Web, bấm vào link WSGI configuration file và thay toàn bộ nội dung bằng:

```python
import os
import sys

path = '/home/<username>/sn-sdk-claude-demo/codevault'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DJANGO_DEBUG'] = '0'
os.environ['DJANGO_SECRET_KEY'] = '<dan-chuoi-secret-ngau-nhien-vao-day>'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Tạo secret key ngẫu nhiên bằng lệnh này trong console:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 6. Map static files

Trong tab Web, phần **Static files**, thêm đúng **một** dòng:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/<username>/sn-sdk-claude-demo/codevault/staticfiles` |

> **Quan trọng:** KHÔNG map `/media/`. File upload (screenshot, XML) được serve qua view có kiểm tra đăng nhập của Django. Nếu map `/media/` thành static files thì bất kỳ ai có URL đều xem được screenshot code công ty của bạn.

### 7. Reload

Bấm nút **Reload** ở đầu tab Web, rồi mở `https://<username>.pythonanywhere.com`.

### Cập nhật code sau này

```bash
cd ~/sn-sdk-claude-demo && git pull
workon codevault
cd codevault
python manage.py migrate
python manage.py collectstatic --no-input
```

rồi bấm **Reload** trên tab Web.

## Workflow gợi ý

1. **Máy công ty**: mở web → New item → Ctrl+V screenshot hoặc paste code/XML → ghi note câu hỏi định hỏi Claude → Save.
2. **Máy cá nhân**: mở web → mở item → bấm **Copy** (hoặc Download file) → paste vào Claude / Claude Code để phân tích.

## Lưu ý bảo mật

- Dùng mật khẩu mạnh cho tài khoản Django (dữ liệu là code nội bộ công ty).
- `DJANGO_DEBUG=0` và secret key riêng khi chạy trên PythonAnywhere (như hướng dẫn trên).
- Trang có `noindex` để không bị search engine index, nhưng bảo vệ thật sự vẫn là login.
- Cân nhắc policy bảo mật của công ty bạn trước khi đưa code/screenshot nội bộ ra hệ thống bên ngoài.
