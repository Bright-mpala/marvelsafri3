import logging
import hashlib
import random
import string
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import User, EmailVerification

logger = logging.getLogger(__name__)

VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_EXPIRY_MINUTES = getattr(settings, 'VERIFICATION_CODE_EXPIRY_MINUTES', 15)


def generate_verification_code() -> str:
    """Generate a random 6-digit verification code."""
    return ''.join(random.choices(string.digits, k=VERIFICATION_CODE_LENGTH))


def hash_verification_code(code: str) -> str:
    """Hash a verification code before storing or comparing it."""
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def create_email_verification(user: User) -> Tuple[EmailVerification, str]:
    """Create or update email verification for user."""
    raw_code = generate_verification_code()
    hashed_code = hash_verification_code(raw_code)
    expires_at = timezone.now() + timedelta(minutes=VERIFICATION_CODE_EXPIRY_MINUTES)
    
    verification, _created = EmailVerification.objects.update_or_create(
        user=user,
        defaults={
            'code': hashed_code,
            'expires_at': expires_at,
            'is_used': False
        }
    )
    
    return verification, raw_code


def send_verification_email(user: User, request=None) -> bool:
    """Send verification code to user's email."""
    verification, code = create_email_verification(user)
    
    # Build verification URL
    if request:
        verification_url = request.build_absolute_uri(
            reverse('accounts:verify_email')
        )
    else:
        verification_url = 'http://localhost:8000/accounts/verify/'
    
    context = {
        'user': user,
        'code': code,
        'verification_url': verification_url,
        'expiry_minutes': VERIFICATION_CODE_EXPIRY_MINUTES,
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@marvelsafari.com'),
    }
    
    # Always log the code in development
    logger.info(
        '\n\n'
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        '  EMAIL VERIFICATION CODE\n'
        '  User : %s\n'
        '  Code : %s\n'
        '  Expires in: %s minutes\n'
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n',
        user.email,
        code,
        VERIFICATION_CODE_EXPIRY_MINUTES,
    )
    
    subject = 'Verify your email - Marvel Safari'
    text_body = render_to_string('accounts/emails/verification_email.txt', context)
    html_body = render_to_string('accounts/emails/verification_email.html', context)
    
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@marvelsafari.com')
    
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[user.email],
    )
    message.attach_alternative(html_body, 'text/html')
    
    try:
        message.send()
        logger.info('Verification email sent to %s', user.email)
        return True
    except Exception as e:
        logger.exception('Failed to send verification email to %s: %s', user.email, str(e))
        return False


def verify_email_code(user: User, code: str) -> Tuple[bool, Optional[str]]:
    """Verify the email verification code."""
    try:
        verification = EmailVerification.objects.get(user=user)
        
        if verification.is_used:
            return False, 'This code has already been used.'
        
        if not verification.is_valid():
            return False, 'This code has expired. Please request a new one.'

        if verification.code != hash_verification_code(code):
            return False, 'Invalid verification code.'
        
        # Mark as used and verify user
        verification.is_used = True
        verification.save()
        
        user.is_email_verified = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=['is_email_verified', 'email_verified_at'])
        
        return True, 'Email verified successfully!'
    
    except EmailVerification.DoesNotExist:
        return False, 'Invalid verification code.'


def cleanup_expired_verifications():
    """Delete expired verification codes (run via cron/periodic task)."""
    expired = EmailVerification.objects.filter(
        expires_at__lt=timezone.now()
    ).delete()
    logger.info(f'Cleaned up {expired[0]} expired verification codes')
