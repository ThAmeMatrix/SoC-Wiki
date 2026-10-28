
data_table={
sword_sr:[26,0,12,6,70,4.44,0,1.62,1.12,11,8.4,0,3,2,21.9]
};

function selectmousedown(ev) {
  if (ev.options.length > 5) {
    ev.size = 6;
    $(ev).css({
      "height": "auto",
      "position": "absolute"
    })
  } else {
    $(ev).css("height", "28px")
  }
}

function selectblur(ev) {
  ev.size = 0;
  $(ev).css({
    "height": "28px",
    "width": "50px",
    "position": "static"
  })
}

function selectchange(ev) {
  ev.size = 0;
  $(ev).css({
    "height": "28px",
    "width": "50px",
    "position": "static"
  })
}

function viewModel() {
    var self = this;
    self.等级 = ko.observable();
    self.星级 = ko.observable();
    self.分类 = document.getElementById("PNN").innerHTML;
    self.data = data_table[self.分类]
    
    <!-- self.物攻 = ko.computed(function() {
    return parseInt((Number(self.等级())-1)*self.data[5] + self.data[0] + (Number(self.星级())-1)*self.data[10]);
  }); 
    self.魔攻 = ko.computed(function() {
    return parseInt((Number(self.等级())-1)*self.data[6] + self.data[1] + (Number(self.星级())-1)*self.data[11]);
  }); 
    self.物防 = ko.computed(function() {
    return parseInt((Number(self.等级())-1)*self.data[7] + self.data[2] + (Number(self.星级())-1)*self.data[12]);
  }); 
    self.魔防 = ko.computed(function() {
    return parseInt((Number(self.等级())-1)*self.data[8] + self.data[3] + (Number(self.星级())-1)*self.data[13]);
  }); 
    self.生命 = ko.computed(function() {
    return parseInt((Number(self.等级())-1)*self.data[9] + self.data[4] + (Number(self.星级())-1)*self.data[14]);
  }); --> 
}

ko.applyBindings(new viewModel());
