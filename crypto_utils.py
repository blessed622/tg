# utils/crypto.py - утилиты для шифрования/дешифрования данных

from cryptography.fernet import Fernet
import base64
import os
from config import ENCRYPTION_KEY


def get_fernet_key():
    """
    Получение ключа для шифрования.
    Если ключ не существует в конфиге или невалидный, генерируется новый.
    """
    key = ENCRYPTION_KEY
    
    # Если ключа нет или он некорректный, генерируем новый
    if not key or len(key) < 32:
        key = Fernet.generate_key().decode()
        print(f"ВНИМАНИЕ: Сгенерирован новый ключ шифрования: {key}")
        print("Рекомендуется обновить значение ENCRYPTION_KEY в config.py")
    
    # Преобразуем ключ в правильный формат для Fernet
    if len(key) < 32:
        # Дополняем ключ до нужной длины
        key = key.ljust(32, '0')
    elif len(key) > 32:
        # Обрезаем ключ до нужной длины
        key = key[:32]
    
    # Преобразуем в URL-safe base64
    key_bytes = key.encode()
    key_base64 = base64.urlsafe_b64encode(key_bytes.ljust(32))
    
    return key_base64


def encrypt_data(data):
    """
    Шифрование данных с использованием Fernet (симметричное шифрование)
    
    Args:
        data (str): Строка с данными для шифрования
        
    Returns:
        str: Зашифрованная строка в base64
    """
    key = get_fernet_key()
    cipher = Fernet(key)
    encrypted_data = cipher.encrypt(data.encode()).decode()
    return encrypted_data


def decrypt_data(encrypted_data):
    """
    Дешифрование данных
    
    Args:
        encrypted_data (str): Зашифрованная строка в base64
        
    Returns:
        str: Расшифрованная строка
    """
    key = get_fernet_key()
    cipher = Fernet(key)
    try:
        decrypted_data = cipher.decrypt(encrypted_data.encode()).decode()
        return decrypted_data
    except Exception as e:
        print(f"Ошибка при дешифровании данных: {e}")
        return None
