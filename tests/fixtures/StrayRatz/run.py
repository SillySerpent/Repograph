from app import create_app
from datetime import datetime
from config import DevelopmentConfig, ProductionConfig, Config
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Use ProductionConfig when ENV is set to production, otherwise use Config
env = os.environ.get('ENV', 'development')
config_class = ProductionConfig if env == 'production' else Config

app = create_app(config_class)

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

if __name__ == '__main__':
    port = int(os.environ.get('FLASK_RUN_PORT', 5001))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', debug=debug, port=port) 