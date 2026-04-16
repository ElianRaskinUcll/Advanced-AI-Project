def select_person():
    """Display a menu to select between two people."""
    people = {
        "1": "Elian Raskin",
        "2": "Ralph Bogaert"
    }
    
    print("\n" + "="*40)
    print("Who are you?")
    print("="*40)
    for key, name in people.items():
        print(f"  {key}. {name}")
    print("="*40)
    
    while True:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        if choice in people:
            selected = people[choice]
            print(f"\n Hello there, {selected}!\n")
            return selected
        else:
            print("Invalid choice. Please enter 1 or 2.")

if __name__ == "__main__":
    select_person()
