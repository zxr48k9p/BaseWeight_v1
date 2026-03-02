from app import app, db, User

def list_users():
    """Print all registered users."""
    with app.app_context():
        users = User.query.all()
        print("\n--- Registered Users ---")
        print(f"{'ID':<5} {'Username':<20}")
        print("-" * 25)
        for user in users:
            print(f"{user.id:<5} {user.username:<20}")
        print("-" * 25)

def reset_password():
    """Reset a specific user's password."""
    username = input("Enter the username to reset: ")
    new_password = input("Enter the new password: ")
    
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if user:
            user.set_password(new_password)
            db.session.commit()
            print(f"\nSUCCESS: Password for '{username}' has been updated.")
        else:
            print(f"\nERROR: User '{username}' not found.")

if __name__ == "__main__":
    while True:
        print("\n=== User Management Tool ===")
        print("1. List all users")
        print("2. Reset a user's password")
        print("3. Exit")
        
        choice = input("\nSelect an option (1-3): ")
        
        if choice == '1': list_users()
        elif choice == '2': reset_password()
        elif choice == '3': break
        else: print("Invalid option.")