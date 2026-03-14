# Authentication Setup Documentation

## Overview
The Marvel Safari travel booking platform uses a **dual authentication system** with both custom Django authentication and django-allauth integrated for flexibility and social login support.

## Authentication Systems

### 1. Custom Authentication (`accounts` app)
- **URL Pattern**: `/auth/`
- **Login**: `/auth/login/`
- **Register**: `/auth/register/`
- **Dashboard**: `/auth/dashboard/`
- **Backend**: `django.contrib.auth.backends.ModelBackend`
- **Forms**: CustomUserCreationForm, CustomUserChangeForm
- **Features**: Custom user registration with extended profile data

### 2. django-allauth Integration (`account` app)
- **URL Pattern**: `/accounts/`
- **Login**: `/accounts/login/`
- **Register**: `/accounts/signup/`
- **Backend**: `allauth.account.auth_backends.AuthenticationBackend`
- **Features**: Social authentication (Google), email verification, account management

## Registration Flow

### Custom Registration (`/auth/register/`)
**User Registration Process:**
1. User fills registration form with:
   - Email
   - First Name
   - Last Name
   - Phone Number (new)
   - Date of Birth (new)
   - Country (new)
   - Password
   - Confirm Password

2. Form Validation:
   - Email uniqueness check
   - Password strength validation
   - Password confirmation match
   - Required fields validation

3. User Creation:
   - User object created with email and name
   - Extended profile data saved:
     - `phone_number`
     - `date_of_birth`
     - `country`
   - User account set as active

4. Auto-Login:
   - User automatically logged in after successful registration
   - Backend explicitly specified: `ModelBackend`
   - **Important**: Multiple auth backends configured, so explicit backend required

5. Dashboard Redirect:
   - User redirected to `/auth/dashboard/`
   - Profile data displayed immediately
   - Confirmation message shown with user's name

**Template**: `templates/accounts/register.html`
- Modern design with Marvel Safari branding
- Yellow (#feba02) and Blue (#003580) color scheme
- Rounded input fields
- Error handling with red boxes
- Sign-in link at bottom

### Custom Login (`/auth/login/`)
**Login Process:**
1. User enters email and password
2. Form validates credentials
3. User authenticated with `ModelBackend`
4. Session created and user logged in
5. Redirect to dashboard or next parameter

**Template**: `templates/accounts/login.html`
- Matches modern registration design
- Error handling for invalid credentials
- "Create Account" link for new users
- Consistent branding and styling

### Allauth Registration (`/accounts/signup/`)
**Features:**
- Google OAuth integration
- Email verification workflow
- Social account linking
- Account management interface

**Template**: `templates/account/signup.html`
- Modern design matching custom registration
- Google sign-up button
- Consistent branding

### Allauth Login (`/accounts/login/`)
**Features:**
- Email/password authentication
- Social login support
- Account recovery options
- Session management

**Template**: `templates/account/login.html`
- Modern design with Marvel Safari branding
- Social login integration
- Sign-up link for new users
- Consistent styling with registration

## User Model Extended Fields

The custom User model includes these fields beyond Django's default:
```python
phone_number = CharField(max_length=20, blank=True)
date_of_birth = DateField(null=True, blank=True)
country = CharField(max_length=100, blank=True)
```

These are:
- Captured during registration
- Stored in user profile
- Displayed on dashboard
- Used in booking confirmation

## Authentication Backends Configuration

**Configured in `settings.py`:**
```python
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',        # Default Django auth
    'allauth.account.auth_backends.AuthenticationBackend',  # Allauth
    'guardian.backends.ObjectPermissionBackend',        # Object permissions
]
```

**Why Multiple Backends?**
- Custom registration uses ModelBackend
- Allauth uses its own backend
- Guardian enables object-level permissions
- **Important**: When calling `login()`, must specify backend explicitly if multiple are configured

## Views Configuration

### UserRegistrationView (CustomUserCreationForm)
```python
class UserRegistrationView(CreateView):
    form_class = CustomUserCreationForm
    template_name = 'accounts/register.html'
    success_url = None  # Set dynamically in form_valid
    
    def form_valid(self, form):
        response = super().form_valid(form)
        # Auto-login with explicit backend
        login(self.request, self.object, 
              backend='django.contrib.auth.backends.ModelBackend')
        # Set success URL to dashboard
        self.success_url = reverse_lazy('accounts:dashboard')
        messages.success(self.request, f"Welcome, {self.object.first_name}!")
        return response
```

**Key Points:**
- Explicit backend specification prevents "Multiple backends available" error
- Dashboard redirect allows user to see saved profile data immediately
- Success message includes user's name

## Navigation Links

### Custom Auth Links
```html
<!-- Login link -->
<a href="{% url 'accounts:login' %}">Sign In</a>

<!-- Registration link -->
<a href="{% url 'accounts:register' %}">Create Account</a>

<!-- Dashboard link (authenticated only) -->
<a href="{% url 'accounts:dashboard' %}">Dashboard</a>
```

### Allauth Links
```html
<!-- Login link -->
<a href="{% url 'account_login' %}">Sign In</a>

<!-- Signup link -->
<a href="{% url 'account_signup' %}">Create Account</a>
```

## Design Consistency

All authentication templates follow the Marvel Safari brand:

**Color Scheme:**
- Primary: #003580 (Dark Blue)
- Accent: #feba02 (Yellow)
- Background: Gray (rgb(249, 250, 251))
- Error: Red (rgb(254, 226, 226))

**Layout:**
- Centered form in full viewport height
- Maximum width 448px (md:w-full max-w-md)
- Brand name in header (Marvel + Safari in two colors)
- Error messages in red boxes with rounded corners
- Rounded input fields with focus states
- Buttons with icon and text
- Social login dividers (desktop only)

**Templates Using Design:**
1. `templates/accounts/register.html` - Custom registration
2. `templates/accounts/login.html` - Custom login
3. `templates/account/signup.html` - Allauth signup
4. `templates/account/login.html` - Allauth login

## User Profile Data Display

### Dashboard View (`accounts:dashboard`)
Displays user's registered information:
- Full Name (First + Last)
- Email
- Phone Number
- Date of Birth
- Country
- Member since date

### Edit Profile
Users can update profile information at:
`/auth/profile/` - Edit all custom profile fields

## Security Notes

1. **Password Storage**: All passwords hashed using Django's default password hasher (PBKDF2)
2. **Session Security**: Django session framework with secure cookie settings
3. **CSRF Protection**: All forms include CSRF token
4. **Email Verification**: Optional with allauth (can be configured)
5. **Social OAuth**: Google OAuth 2.0 through django-allauth

## Testing Registration Flow

```bash
# Test custom registration
python manage.py test accounts.tests.UserRegistrationTest

# Test with valid data
POST /auth/register/
- email: user@example.com
- first_name: John
- last_name: Doe
- phone_number: +1234567890
- date_of_birth: 1990-01-15
- country: USA
- password1: SecurePass123!
- password2: SecurePass123!

# Expected outcome:
- User created in database
- User logged in automatically
- Redirect to /auth/dashboard/
- Dashboard shows all profile data
```

## Troubleshooting

### "Reverse for 'register' not found"
- Check URL namespace in template
- Custom auth: `{% url 'accounts:register' %}`
- Allauth: `{% url 'account_signup' %}`

### "Multiple authentication backends without explicit backend parameter"
- Specify backend in login() call
- `login(request, user, backend='django.contrib.auth.backends.ModelBackend')`

### OAuth Not Working
- Verify Google OAuth credentials in admin
- Check `Site` objects match domain
- Ensure socialaccount_providers loaded

### Profile Data Not Saving
- Verify User model has extended fields defined
- Check form's save() method processes all fields
- Confirm model migration applied

## Future Improvements

1. Add email verification for custom registration
2. Consolidate to single authentication system (reduce duplication)
3. Add two-factor authentication
4. Implement password complexity rules
5. Add login attempt throttling
6. Create unified authentication dashboard
