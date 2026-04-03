# StrayRatz Landing Page

A Flask-based landing page for StrayRatz, an all-in-one supplement solution combining pre-workout, protein, BCAAs, and creatine.

## Features

- Responsive landing page showcasing the product
- User registration and authentication
- Newsletter subscription collection
- Product survey for customer feedback
- Admin dashboard to view collected data
- SQLite database for data storage

## Installation

1. Clone the repository:
```
git clone https://github.com/yourusername/StrayRatz.git
cd StrayRatz
```

2. Create and activate a virtual environment:
```
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```
pip install -r requirements.txt
```

4. Run the application:
```
python run.py
```

5. Access the application in your browser at `http://127.0.0.1:5001/`

## Default Admin Account

Upon first run, the application creates a default admin account:
- Username: admin
- Email: admin@strayratz.com
- Password: adminpassword123

**Important:** Change this password after first login in a production environment.

## Project Structure

```
StrayRatz/
├── app/
│   ├── static/
│   │   ├── css/
│   │   │   └── styles.css
│   │   ├── js/
│   │   │   └── main.js
│   │   └── img/
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── survey.html
│   │   ├── register.html
│   │   ├── login.html
│   │   ├── admin/
│   │   │   ├── dashboard.html
│   │   │   ├── users.html
│   │   │   ├── newsletters.html
│   │   │   └── surveys.html
│   ├── __init__.py
│   ├── models.py
│   ├── routes.py
│   ├── forms.py
│   └── admin.py
├── instance/
│   └── site.db
├── config.py
├── requirements.txt
└── run.py
```

## Technologies Used

- Backend: Flask, SQLAlchemy
- Frontend: HTML5, CSS3, JavaScript, Bootstrap 5
- Database: SQLite
- Forms: Flask-WTF
- Authentication: Flask-Login

## License

This project is licensed under a License - see the LICENSE file for details. 
