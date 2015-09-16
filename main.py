import threading
import datetime
import ConfigParser

import wx
from wx.lib.newevent import NewEvent
import wx.lib.masked as masked
import stripe
stripe.http_client.urlfetch = None


CustomersFetchedEvent, EVT_CUSTOMERS_FETCHED = NewEvent()
CustomerDetailEvent, EVT_CUSTOMER_DETAIL = NewEvent()
AddCustomerEvent, EVT_ADD_CUSTOMER = NewEvent()
AddCardEvent, EVT_ADD_CARD = NewEvent()


def fetch_customers(win):
    customers = []
    response = stripe.Customer.all()
    while True:
        for customer in response.data:
            customers.append(customer)
        if not response.has_more:
            break
        lastid = response.data[-1].id
        response = stripe.Customer.all(starting_after=lastid)
    wx.PostEvent(win, CustomersFetchedEvent(customers=customers))

def fetch_detail(win, customer):
    cards = []
    response = customer.sources.all()
    while True:
        for card in response.data:
            cards.append(card)
        if not response.has_more:
            break
        lastid = response.data[-1].id
        response = customer.sources.all(starting_after=lastid)
    
    charges = []
    response = stripe.Charge.all(customer=customer.id)
    while True:
        for charge in response.data:
            charges.append(charge)
        if not response.has_more:
            break
        lastid = response.data[-1].id
        response = stripe.Charge.all(customer=id, starting_after=lastid)
    wx.PostEvent(win, CustomerDetailEvent(
        customer=customer, cards=cards, charges=charges))

def add_customer(win, email, description):
    customer = stripe.Customer.create(email=email, description=description)
    wx.PostEvent(win, AddCustomerEvent(customer=customer))

def add_card(win, customer, number, exp_month, exp_year, cvc=None):
    card = {
        'object': 'card',
        'number': int(number),
        'exp_month': int(exp_month),
        'exp_year': int(exp_year)}
    if cvc:
        card['cvc'] = int(cvc)
    try:
        card = customer.sources.create(source=card)
    except stripe.error.CardError, e:
        wx.PostEvent(win, AddCardEvent(error=e, card=None))
    else:
        wx.PostEvent(win, AddCardEvent(error=None, card=card))


class MainFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(MainFrame, self).__init__(*args, **kwargs)
        self.load_config()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(EVT_CUSTOMERS_FETCHED, self.on_customers_fetched)
        self.Bind(EVT_CUSTOMER_DETAIL, self.on_detail_fetched)

        hbox = wx.BoxSizer(wx.HORIZONTAL)

        self.customer_list = CustomerList(self)
        hbox.Add(self.customer_list, 0, wx.EXPAND)

        self.customer_detail = CustomerDetail(self)
        hbox.Add(self.customer_detail, 1, wx.EXPAND)

        self.SetSizer(hbox)
        
        self.load_customers()
        self.Fit()

    def load_config(self):
        self.config = ConfigParser.SafeConfigParser()
        self.config.read('settings.cfg')
        stripe.api_key = self.config.get('Stripe', 'api_key')
        try:
            self.config.add_section('Stripe')
        except ConfigParser.DuplicateSectionError:
            pass

    def save_config(self):
        with open('settings.cfg', 'wb') as configfile:
            self.config.write(configfile)

    def on_customer_selected(self, customer):
        self.customer_list.Disable()
        self.customer_detail.Disable()
        t = threading.Thread(target=fetch_detail, args=(self, customer))
        t.setDaemon(True)
        t.start()
        return

    def on_close(self, e):
        self.save_config()
        e.Skip()

    def on_customers_fetched(self, e):
        self.customer_list.set_customers(e.customers)
        self.customer_list.Enable()
        self.Layout()

    def on_detail_fetched(self, e):
        self.customer_detail.set_detail(e.customer, e.cards, e.charges)
        self.customer_list.Enable()
        self.customer_detail.Enable()
        self.Layout()

    def load_customers(self):
        self.customer_list.Disable()
        self.customer_detail.Disable()
        self.customer_detail.set_detail(None, None, None)
        t = threading.Thread(target=fetch_customers, args=(self,))
        t.setDaemon(True)
        t.start()


class CustomerList(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(CustomerList, self).__init__(*args, **kwargs)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        label = wx.StaticText(self, label='Customers')
        vbox.Add(label, 0, wx.ALIGN_CENTER|wx.ALL, 10)
        
        self.listbox = wx.ListBox(self, style=wx.LB_SINGLE | wx.LB_SORT)
        self.listbox.Bind(wx.EVT_LISTBOX, self.on_selection)
        vbox.Add(self.listbox, 1, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)

        add_button = wx.Button(self, label='Add Customer')
        add_button.Bind(wx.EVT_BUTTON, self.on_add)
        vbox.Add(add_button, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)

        button = wx.Button(self, label='Reload')
        button.Bind(wx.EVT_BUTTON, self.on_refresh)
        vbox.Add(button, 0, wx.EXPAND|wx.ALL, 10)

        self.SetSizer(vbox)

    def set_customers(self, customers):
        self.customers = customers
        self.listbox.Set([c.email for c in customers])

    def add_customer(self, customer):
        self.customers.append(customer)
        self.listbox.Set([c.email for c in self.customers])

    def on_add(self, e):
        dialog = AddCustomerDialog(self, title='Add Customer')
        dialog.ShowModal()
        dialog.Destroy()

    def on_refresh(self, e):
        self.Parent.load_customers()

    def on_selection(self, e):
        selection = self.listbox.GetStringSelection()
        for customer in self.customers:
            if selection == customer.email:
                self.Parent.on_customer_selected(customer)
                return


class CustomerDetail(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(CustomerDetail, self).__init__(*args, **kwargs)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.code = wx.StaticText(self)
        font = self.code.GetFont()
        font.MakeBold().SetPointSize(18)
        self.code.SetFont(font)
        vbox.Add(self.code, 0, wx.ALIGN_CENTER|wx.ALL, 10)

        self.name = wx.StaticText(self)
        vbox.Add(self.name, 0, wx.ALIGN_CENTER|wx.LEFT|wx.RIGHT, 10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        cards = wx.StaticText(self, label='Cards')
        hbox.Add(cards, flag=wx.ALIGN_BOTTOM)
        hbox.AddStretchSpacer(1)
        add_card = wx.Button(self, label='Add Card')
        add_card.Bind(wx.EVT_BUTTON, self.on_add_card)
        hbox.Add(add_card)
        vbox.Add(hbox, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)

        self.cards_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.cards_list.InsertColumn(0, 'Card Info')
        self.cards_list.InsertColumn(1, 'Expiration')
        vbox.Add(self.cards_list, 1, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        charges = wx.StaticText(self, label='Charges')
        hbox.Add(charges, flag=wx.ALIGN_BOTTOM)
        hbox.AddStretchSpacer(1)
        create_charge = wx.Button(self, label='Create Charge')
        create_charge.Bind(wx.EVT_BUTTON, self.on_create_charge)
        hbox.Add(create_charge)
        vbox.Add(hbox, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)

        self.charges_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.charges_list.InsertColumn(0, 'Date')
        self.charges_list.InsertColumn(1, 'Amount')
        self.charges_list.InsertColumn(2, 'Card Info')
        self.charges_list.InsertColumn(3, 'Expiration')
        self.charges_list.InsertColumn(4, 'Status')
        vbox.Add(self.charges_list, 1, wx.EXPAND|wx.ALL, 10)

        self.SetSizer(vbox)
        self.Disable()

    def set_detail(self, customer, cards, charges):
        self.customer = customer
        self.cards = cards
        self.charges = charges
        if customer:
            self.code.SetLabel(customer.email)
            self.name.SetLabel(customer.description)
        else:
            self.code.SetLabel('')
            self.name.SetLabel('')
        self.cards_list.DeleteAllItems()
        if cards:
            for index, card in enumerate(cards):
                cardstr = '%s ending in %s' % (card.brand, card.last4)
                exp = '%s/%s' % (card.exp_month, card.exp_year)
                self.cards_list.InsertStringItem(index, cardstr)
                self.cards_list.SetStringItem(index, 1, exp)
            self.cards_list.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
            self.cards_list.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        self.charges_list.DeleteAllItems()
        if charges:
            for index, charge in enumerate(charges):
                date = datetime.date.fromtimestamp(charge.created)
                date = date.strftime('%x')
                amt = charge.amount / 100
                amt = '${0:.02f}'.format(amt)
                card = '%s ending in %s' % (charge.source.brand,
                    charge.source.last4)
                exp = '%s/%s' % (charge.source.exp_month,
                    charge.source.exp_year)
                stat = 'Success' if charge.status == 'succeeded' else 'Failed'
                self.charges_list.InsertStringItem(index, date)
                self.charges_list.SetStringItem(index, 1, amt)
                self.charges_list.SetStringItem(index, 2, card)
                self.charges_list.SetStringItem(index, 3, exp)
                self.charges_list.SetStringItem(index, 4, stat)
            self.charges_list.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
            self.charges_list.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
            self.charges_list.SetColumnWidth(2, wx.LIST_AUTOSIZE_USEHEADER)
            self.charges_list.SetColumnWidth(3, wx.LIST_AUTOSIZE_USEHEADER)
            self.charges_list.SetColumnWidth(4, wx.LIST_AUTOSIZE_USEHEADER)

    def add_card(self, card):
        self.cards.insert(0, card)
        cardstr = '%s ending in %s' % (card.brand, card.last4)
        exp = '%s/%s' % (card.exp_month, card.exp_year)
        self.cards_list.InsertStringItem(0, cardstr)
        self.cards_list.SetStringItem(0, 1, exp)
        self.cards_list.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.cards_list.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)

    def on_add_card(self, e):
        dialog = AddCardDialog(self, title='Add Credit Card')
        dialog.ShowModal()
        dialog.Destroy()

    def on_create_charge(self, e):
        print 'create charge'


class AddCustomerDialog(wx.Dialog):
    def __init__(self, *args, **kwargs):
        super(AddCustomerDialog, self).__init__(*args, **kwargs)
        vbox = wx.BoxSizer(wx.VERTICAL)

        code = wx.StaticText(self, label='Customer Code')
        vbox.Add(code, 0, wx.ALL, 10)

        self.code_entry = wx.TextCtrl(self)
        vbox.Add(self.code_entry, 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)

        name = wx.StaticText(self, label='Customer Name')
        vbox.Add(name, 0, wx.TOP|wx.LEFT|wx.RIGHT, 10)

        self.name_entry = wx.TextCtrl(self)
        vbox.Add(self.name_entry, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)

        hbox = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_add, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)
        vbox.Add(hbox, 0, wx.ALL, 10)

        self.SetSizer(vbox)
        self.Fit()
        self.Bind(EVT_ADD_CUSTOMER, self.on_customer_added)
        self.code_entry.SetFocus()

    def on_add(self, e):
        self.Disable()
        email = self.code_entry.GetValue()
        desc = self.name_entry.GetValue()
        if not (email and desc):
            wx.MessageBox('Must supply customer code and customer name.',
                'Error', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        elif email in (c.email for c in self.Parent.customers):
            wx.MessageBox('Customer already exists.',
                'Error', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=add_customer, args=(self, email, desc))
        t.setDaemon(True)
        t.start()

    def on_cancel(self, e):
        self.Destroy()

    def on_customer_added(self, e):
        self.Parent.add_customer(e.customer)
        self.Destroy()


class AddCardDialog(wx.Dialog):
    default_mask = '#### #### #### ####'
    amex_mask = '#### ###### #####'
    default_cvc = '###'
    amex_cvc = '####'

    def __init__(self, *args, **kwargs):
        super(AddCardDialog, self).__init__(*args, **kwargs)
        vbox = wx.BoxSizer(wx.VERTICAL)

        card_num = wx.StaticText(self, label='Credit Card Number')
        vbox.Add(card_num, 0, wx.ALL, 10)

        self.cc_num = masked.TextCtrl(self, mask=self.default_mask)
        self.cc_num.Bind(wx.EVT_TEXT, self.on_card_changed)
        vbox.Add(self.cc_num, 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)

        self.month = wx.Choice(self, choices=[str(n) for n in range(1, 13)])
        vbox.Add(self.month)

        hbox = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_add, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)
        vbox.Add(hbox, 0, wx.ALL, 10)
        
        self.SetSizer(vbox)
        self.Fit()

    def on_card_changed(self, e):
        value = self.cc_num.GetPlainValue()
        current_mask = self.cc_num.GetMask()
        if value.startswith('3'):
            if current_mask != self.amex_mask:
                self.cc_num.SetMask(self.amex_mask)
                self.cc_num.ChangeValue(value)
        elif current_mask != self.default_mask:
            self.cc_num.SetMask(self.default_mask)
            self.cc_num.ChangeValue(value)

    def on_add(self, e):
        self.Disable()
        number = self.cc_num.GetPlainValue()

        self.Destroy()

    def on_cancel(self, e):
        self.Destroy()


if __name__ == '__main__':
    app = wx.App() ### Log output to file ### (True, 'output.log')
    frame = MainFrame(None, title='Stripe Card Terminal')
    frame.Show()
    app.MainLoop()
