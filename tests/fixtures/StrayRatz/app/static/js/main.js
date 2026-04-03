// HydraFuel JavaScript Functionality

document.addEventListener('DOMContentLoaded', function() {
    // Initialize AOS
    AOS.init({
        duration: 800,
        easing: 'ease-in-out',
        once: true
    });

    // Simple newsletter popup logic - show only once
    if (!localStorage.getItem('newsletterShown')) {
        setTimeout(function() {
            const newsletterModal = document.getElementById('newsletterModal');
            if (newsletterModal) {
                const modal = new bootstrap.Modal(newsletterModal);
                modal.show();
                localStorage.setItem('newsletterShown', 'true');
                
                // Make sure the modal is properly hidden when closed
                newsletterModal.addEventListener('hidden.bs.modal', function () {
                    document.body.classList.remove('modal-open');
                    const modalBackdrop = document.querySelector('.modal-backdrop');
                    if (modalBackdrop) {
                        modalBackdrop.remove();
                    }
                });
            }
        }, 5000);
    }

    // Newsletter subscription form handling
    const newsletterForm = document.getElementById('newsletterForm');
    if (newsletterForm) {
        newsletterForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const url = '/api/subscribe';
            
            // Add CSRF token
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            formData.append('csrf_token', csrfToken);
            
            fetch(url, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('newsletterSuccess').classList.remove('d-none');
                    newsletterForm.reset();
                    
                    // Hide the form
                    const formElements = newsletterForm.querySelectorAll('input, button');
                    formElements.forEach(el => {
                        el.parentElement.style.display = 'none';
                    });
                    
                    // Close the modal after 2 seconds
                    setTimeout(function() {
                        const newsletterModal = document.getElementById('newsletterModal');
                        if (newsletterModal) {
                            const modal = bootstrap.Modal.getInstance(newsletterModal);
                            if (modal) modal.hide();
                        }
                    }, 2000);
                } else {
                    document.getElementById('newsletterError').textContent = data.message;
                    document.getElementById('newsletterError').classList.remove('d-none');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                document.getElementById('newsletterError').textContent = 'An unexpected error occurred. Please try again.';
                document.getElementById('newsletterError').classList.remove('d-none');
            });
        });
    }
    
    // Navbar behavior on scroll
    window.addEventListener('scroll', function() {
        const navbar = document.querySelector('.navbar');
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });
    
    // Initiate the carousel
    var heroCarousel = document.querySelector('#heroCarousel')
    if (heroCarousel) {
        var carousel = new bootstrap.Carousel(heroCarousel, {
            interval: 5000,
            wrap: true
        })
    }

    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            if (targetId === '#') return;
            
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                targetElement.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });

    // Add active class to nav items
    const currentPage = window.location.pathname;
    document.querySelectorAll('.navbar-nav .nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPage) {
            link.classList.add('active');
        }
    });
    
    // Form validation enhancement
    const forms = document.querySelectorAll('.needs-validation');
    Array.from(forms).forEach(form => {
        form.addEventListener('submit', event => {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    });
    
    // Interest level radio buttons visual enhancement
    const interestLevels = document.querySelectorAll('input[name="interest_level"]');
    if (interestLevels.length > 0) {
        interestLevels.forEach(radio => {
            radio.addEventListener('change', function() {
                // Remove active class from all labels
                document.querySelectorAll('.form-check-inline').forEach(el => {
                    el.classList.remove('active');
                });
                
                // Add active class to selected label
                if (this.checked) {
                    this.parentElement.classList.add('active');
                }
            });
        });
    }
    
    // Newsletter form AJAX submission (backup for when jQuery might not be loaded)
    const newsletterFormBackup = document.getElementById('newsletter-form');
    if (newsletterFormBackup) {
        newsletterFormBackup.addEventListener('submit', function(e) {
            // If jQuery is handling this, let it continue
            if (window.jQuery) return;
            
            // Otherwise, handle with vanilla JS
            e.preventDefault();
            const formData = new FormData(this);
            const resultDiv = document.getElementById('newsletter-form-result');
            
            // Add CSRF token
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
            formData.append('csrf_token', csrfToken);
            
            fetch('/api/subscribe', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    resultDiv.innerHTML = '<div class="alert alert-success">' + data.message + '</div>';
                    newsletterFormBackup.reset();
                } else {
                    resultDiv.innerHTML = '<div class="alert alert-danger">' + data.message + '</div>';
                }
            })
            .catch(error => {
                console.error('Error:', error);
                resultDiv.innerHTML = '<div class="alert alert-danger">An unexpected error occurred.</div>';
            });
        });
    }
    
    // Animated elements on scroll
    const animateOnScroll = () => {
        const elements = document.querySelectorAll('.animate-on-scroll');
        
        elements.forEach(element => {
            const position = element.getBoundingClientRect();
            
            // If element is in viewport
            if (position.top < window.innerHeight && position.bottom >= 0) {
                element.classList.add('animated');
            }
        });
    };
    
    // Add animation class to elements
    document.querySelectorAll('.feature-card, .testimonial-card').forEach(el => {
        el.classList.add('animate-on-scroll');
    });
    
    // Initial check and add scroll event
    animateOnScroll();
    window.addEventListener('scroll', animateOnScroll);

    // Flavor selector in product section
    const flavorButtons = document.querySelectorAll('.flavor-btn');
    
    if (flavorButtons.length > 0) {
        flavorButtons.forEach(button => {
            button.addEventListener('click', function() {
                // Remove active class from all buttons
                flavorButtons.forEach(btn => btn.classList.remove('active'));
                
                // Add active class to clicked button
                this.classList.add('active');
            });
        });
    }
}); 